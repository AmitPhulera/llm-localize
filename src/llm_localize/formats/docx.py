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
from llm_localize.formats.xml_utils import tag_end
from llm_localize.units import section_context

PART_RE = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
GROUP_RE = re.compile(r"<g(\d+)>(.*?)</g\1>", re.S)
GROUP_TAG_RE = re.compile(r"</?g\d+>")


class _Text:
    """One ``<w:t>``: where its start tag and content are, and its text."""

    def __init__(self, start, inner_start):
        self.start, self.inner_start, self.inner_end = start, inner_start, inner_start
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

    @cached_property
    def _source(self):
        return _read(self.source_path)

    def read_messages(self, path):
        return {key: Message(text=paragraph.message, context=context)
                for key, (paragraph, context) in _messages(_read(path)[1]).items()}

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
                    new = b'<w:t xml:space="preserve">' + (_escape(text) if index == 0 else "").encode()
                    if element.self_closing:
                        new += b"</w:t>"
                    replacements.setdefault(paragraph.part, []).append((element.start, element.inner_end, new))
        package = io.BytesIO()
        with zipfile.ZipFile(self.source_path) as source, zipfile.ZipFile(package, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename in replacements:
                    data = splice(data, replacements[info.filename])
                target.writestr(info, data)
        write_file(self.path, package.getbuffer())


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _messages(paragraphs):
    """Return ``{key: (paragraph, context)}`` for paragraphs with text."""
    messages, headings = {}, []
    for index, paragraph in enumerate(paragraphs):
        text = "".join(paragraph.texts)
        # Text that itself reads like a group tag would split the translation wrongly between runs, or
        # fail the check of them, so a paragraph with such text is left as it is
        if not text.strip() or GROUP_TAG_RE.search(text):
            continue
        context = section_context([title for _, title in headings])
        messages[f"{paragraph.part}:{index}"] = (paragraph, context)
    return messages


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


def _paragraphs(part, data):
    """Return a part's paragraphs, with the position of each ``<w:t>`` and how its run is formatted."""
    parser = expat.ParserCreate()
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
        stack.append((name, start_index, inner_start))
        if name == "p":
            paragraph = _Paragraph(part)
            open_paragraphs.append(paragraph)
            paragraphs.append(paragraph)
        elif not open_paragraphs:
            return
        elif name == "r":
            runs.append(b"")
        elif name == "t" and runs:
            text = _Text(start_index, inner_start)
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
