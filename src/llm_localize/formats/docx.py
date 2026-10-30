"""Word documents (``.docx``), translated into a copy per language, like ``fr/report.docx`` from ``report.docx``.

A .docx file is a ZIP of XML parts. Each paragraph of the body, headers,
footers, footnotes and endnotes is one message. Word splits a paragraph
into runs of differently formatted text (bold, italic, a link), so a
paragraph with more than one is sent with each run's text in a tag,
``<g1>Click </g1><g2>here</g2>``. Old binary ``.doc`` files aren't
supported: convert them first, e.g. with LibreOffice's ``soffice
--headless --convert-to docx``.
"""
from xml.parsers import expat

from llm_localize.formats.xml_utils import tag_end


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


def _paragraphs(part, data):
    """Return a part's paragraphs, with the position of each ``<w:t>`` and how its run is formatted."""
    parser = expat.ParserCreate()
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
