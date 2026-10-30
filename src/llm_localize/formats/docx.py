"""Word documents (``.docx``), translated into a copy per language, like ``fr/report.docx`` from ``report.docx``.

A .docx file is a ZIP of XML parts. Each paragraph of the body, headers,
footers, footnotes and endnotes is one message. Word splits a paragraph
into runs of differently formatted text (bold, italic, a link), so a
paragraph with more than one is sent with each run's text in a tag,
``<g1>Click </g1><g2>here</g2>``, and each run gets its translated text
back. Only the text inside ``<w:t>`` elements is changed, by byte
offset, so the rest of the document is kept exactly. Old binary ``.doc``
files aren't supported: convert them first, e.g. with LibreOffice's
``soffice --headless --convert-to docx``.
"""
import io
import os
import re
import zipfile
import zlib
from collections import Counter
from functools import cached_property
from xml.parsers import expat

from llm_localize.formats.base import splice, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.formats.xml_utils import from_utf8, open_tag, set_attribute, tag_end, to_utf8
from llm_localize.units import TranslationUnit, section_context

PART_RE = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
GROUP_RE = re.compile(r"<g(\d+)>(.*?)</g\1>", re.S)
GROUP_TAG_RE = re.compile(r"</?g\d+>")
HEADING_STYLE_RE = re.compile(r"^(?:heading|Heading)\s*(\d)$")


class _Text:
    """One ``<w:t>``: its name as written, where its start tag and content are, and its text."""

    def __init__(self, start, inner_start, start_tag):
        self.start, self.inner_start, self.inner_end = start, inner_start, inner_start
        self.start_tag = start_tag
        # Like w:t, or t in a document that makes WordprocessingML the default namespace
        self.name = re.match(rb"<([^\s/>]+)", start_tag).group(1)
        self.self_closing = False
        self.text = ""


class _Paragraph:
    def __init__(self, part):
        self.part = part
        self.groups = []  # each a list of _Text with the same formatting and nothing between them
        self.style = ""
        self.open_group = None  # the format key of the group text can still be added to

    def add(self, text, format_key):
        if self.open_group != format_key or not self.groups:
            self.groups.append([])
            self.open_group = format_key
        self.groups[-1].append(text)

    def separate(self):
        self.open_group = None

    @property
    def texts(self):
        return ["".join(text.text for text in group) for group in self.groups]

    @property
    def message(self):
        """The paragraph's text, with each group in a ``<gN>`` tag when there's more than one."""
        texts = self.texts
        if len(texts) == 1:
            return texts[0]
        return "".join(f"<g{index}>{text}</g{index}>" for index, text in enumerate(texts, start=1))


class DocxFile(MonolingualFile):
    name = "docx"
    extensions = (".docx",)

    def source_path_candidates(self):
        yield from super().source_path_candidates()
        # Also without the language: fr/report.docx and report.fr.docx from report.docx
        if self.path_without_language():
            yield self.path_without_language()

    @cached_property
    def _source(self):
        return _read(self.source_path)

    def read_messages(self, path):
        return {key: Message(text=paragraph.message, context=context)
                for key, (paragraph, context) in _messages(_read(path)[1]).items()}

    def untranslated_units(self):
        # The source itself has nothing to translate, and writing a copy over it would destroy it
        if self.is_source:
            return []
        # Every paragraph, every run, as for Markdown: the copy can't be matched to a changed source
        return [TranslationUnit(key=key, source=paragraph.message, context=context)
                for key, (paragraph, context) in _messages(self._source[1]).items()]

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = translation

    def save(self):
        """Write the copy: the source's ZIP, with each translated paragraph's text replaced in its part."""
        parts, paragraphs = self._source
        messages = _messages(paragraphs)
        replacements = {}
        for key, translation in self._applied.items():
            paragraph = messages[key][0]
            texts = [text for _, text in GROUP_RE.findall(translation)] if len(paragraph.groups) > 1 \
                else [translation]
            for group, text in zip(paragraph.groups, texts, strict=True):
                for index, element in enumerate(group):
                    # The whole group's text goes in its first <w:t>, keeping that run's formatting
                    new = _preserving_space(element) + (_escape(text) if index == 0 else "").encode()
                    if element.self_closing:
                        new += b"</" + element.name + b">"
                    replacements.setdefault(paragraph.part, []).append((element.start, element.inner_end, new))
        package = io.BytesIO()
        with zipfile.ZipFile(self.source_path) as source, zipfile.ZipFile(package, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename in replacements:
                    # Offsets are in the part as UTF-8, as it was read; it's written back in its own encoding
                    data, encoding, bom = to_utf8(data, info.filename)
                    data = from_utf8(splice(data, replacements[info.filename]), encoding, bom)
                target.writestr(info, data)
        write_file(self.path, package.getbuffer())


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _messages(paragraphs):
    """Return ``{key: (paragraph, context)}`` for paragraphs with text, with headings above them as context."""
    messages, headings, part = {}, [], None
    for index, paragraph in enumerate(paragraphs):
        if paragraph.part != part:
            # Headers, footers and notes don't sit under the body's headings
            headings, part = [], paragraph.part
        text = "".join(paragraph.texts)
        # Text that itself reads like a group tag would split the translation wrongly between runs, or
        # fail the check of them, so a paragraph with such text is left as it is
        if not text.strip() or GROUP_TAG_RE.search(text):
            continue
        level = _heading_level(paragraph.style)
        if level:
            headings = [(lvl, title) for lvl, title in headings if lvl < level]
        context = section_context([title for _, title in headings])
        messages[f"{paragraph.part}:{index}"] = (paragraph, context)
        if level:
            headings.append((level, text.strip()))
    return messages


def _heading_level(style):
    if style == "Title":
        return 1
    match = HEADING_STYLE_RE.match(style)
    return int(match.group(1)) + 1 if match else 0


def _read(path):
    """Return ``(parts, paragraphs)``: the translatable parts' names, and their paragraphs in order."""
    if not os.path.exists(path):
        return [], []
    try:
        with zipfile.ZipFile(path) as package:
            # A name used twice would be read for each use, past the limit on what an upload unpacks to
            repeated = next((name for name, count in Counter(package.namelist()).items() if count > 1), None)
            if repeated:
                raise ValueError(f"{path} is not a valid .docx file: it has more than one {repeated}")
            # Word doesn't encrypt parts or compress them other ways, and copying them would fail after translating
            unreadable = next((info.filename for info in package.infolist() if info.flag_bits & 0x1
                               or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)), None)
            if unreadable:
                raise ValueError(f"{path} is not a valid .docx file: {unreadable} is encrypted or compressed "
                                 "in a way Word doesn't use")
            # Before any translating: copying a corrupt part when saving would fail after it
            corrupt = package.testzip()
            if corrupt:
                raise ValueError(f"{path} is not a valid .docx file: {corrupt} is corrupt")
            names = [name for name in package.namelist() if PART_RE.match(name)]
            if "word/document.xml" not in names:
                raise ValueError(f"{path} is not a Word document: it has no word/document.xml")
            # The body first, then headers, footers and notes
            names.sort(key=lambda name: (not name.endswith("document.xml"), name))
            paragraphs = []
            for name in names:
                paragraphs.extend(_paragraphs(name, package.read(name)))
    # Like a corrupt deflate stream, or ZIP features Python doesn't support
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as e:
        raise ValueError(f"{path} is not a .docx file: {e}") from e
    return names, paragraphs


def _preserving_space(element):
    """Return a text element's start tag, opened if it closes itself, with xml:space="preserve".

    >>> _preserving_space(_Text(0, 0, b'<w:t xmlns:w="urn:w" xml:space="default"/>'))
    b'<w:t xmlns:w="urn:w" xml:space="preserve">'
    """
    return set_attribute(open_tag(element.start_tag), b"xml:space", b"preserve")


def _paragraphs(part, data):
    """Return a part's paragraphs, with the position of each ``<w:t>`` and how its run is formatted.

    A part in another encoding, like UTF-16, is read as UTF-8, and the
    positions are in that.
    """
    data = to_utf8(data, part)[0]
    parser = expat.ParserCreate("UTF-8")
    # Text in one call, not one per entity like &amp;, which adding up one at a time would make quadratic
    parser.buffer_text = True
    paragraphs, open_paragraphs, stack = [], [], []
    runs = []  # (format key) of each open run
    current_text = []

    def local(tag):
        return tag.rpartition(":")[2]

    def start(tag, attrs):
        name = local(tag)
        start_index = parser.CurrentByteIndex
        inner_start = tag_end(data, start_index)
        parent = stack[-1][0] if stack else ""
        stack.append((name, start_index, inner_start))
        if name == "p":
            paragraph = _Paragraph(part)
            open_paragraphs.append(paragraph)
            paragraphs.append(paragraph)
        elif not open_paragraphs:
            return
        elif name == "pStyle" and parent == "pPr":
            open_paragraphs[-1].style = attrs.get("w:val", "")
        elif name == "r":
            runs.append(b"")
        elif name == "t" and runs:
            text = _Text(start_index, inner_start, data[start_index:inner_start])
            open_paragraphs[-1].add(text, runs[-1])
            current_text.append(text)

    def end(tag):
        name, start_index, inner_start = stack.pop()
        end_index = parser.CurrentByteIndex
        self_closing = data[inner_start - 2:inner_start] == b"/>"
        if name == "p":
            open_paragraphs.pop()
        elif name == "rPr" and stack and stack[-1][0] == "r" and runs:
            runs[-1] = data[start_index:end_index]
        elif name == "r" and runs:
            runs.pop()
        elif name == "t" and current_text:
            text = current_text.pop()
            text.inner_end = inner_start if self_closing else end_index
            text.self_closing = self_closing

    def characters(content):
        if current_text:
            current_text[-1].text += content

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{part} is not valid XML: {e}") from e
    return [paragraph for paragraph in paragraphs if paragraph.groups]
