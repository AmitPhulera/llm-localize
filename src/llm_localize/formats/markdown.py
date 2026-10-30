"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/en/guide.md``.

The document is split into blocks: paragraphs. Each block is one
message.
"""
import re


class _Unit:
    """A translatable block, and how to write its translation back: a prefix per line, and the line ending."""

    def __init__(self, key, text, first_prefix="", prefix="", suffix="", context=""):
        self.key, self.text, self.context = key, text, context
        self.first_prefix, self.prefix, self.suffix = first_prefix, prefix, suffix

    def render(self, translation):
        lines = translation.split("\n")
        return self.first_prefix + "\n".join(
            lines[:1] + [self.prefix + line if line else self.prefix.rstrip() for line in lines[1:]]
        ) + self.suffix


def _read(path):
    with open(path, encoding="utf-8") as f:
        parser = _Parser(f.read())
    parser.parse()
    return parser


def _parse(text):
    """Split a Markdown document into literal strings and ``_Unit`` blocks, which join back into it.

    >>> pieces = _parse("Some *text*.\\n\\nMore.\\n")
    >>> [(piece.text, piece.context) if isinstance(piece, _Unit) else piece for piece in pieces]
    [('Some *text*.', ''), '\\n', ('More.', '')]
    """
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.pieces = []
        self.index = 0

    def unit(self, text, first_prefix="", prefix="", suffix=""):
        if not text.strip():
            self.pieces.append(first_prefix + text + suffix)
            return
        self.pieces.append(_Unit(str(len(self.pieces)), text, first_prefix, prefix, suffix))

    def line(self, offset=0):
        index = self.index + offset
        return self.lines[index].rstrip("\r\n") if index < len(self.lines) else None

    def ending(self, index):
        line = self.lines[index]
        return line[len(line.rstrip("\r\n")):]

    def literal(self, count=1):
        self.pieces.append("".join(self.lines[self.index:self.index + count]))
        self.index += count

    def parse(self):
        while self.index < len(self.lines):
            line = self.line()
            if not line.strip():
                self.literal()
            else:
                self.paragraph()
        return self.pieces

    def paragraph(self):
        indent = re.match(r"[ \t]*", self.line()).group()
        lines = []
        while self.index < len(self.lines):
            current = self.line()
            if not current.strip():
                break
            lines.append(current[len(indent):] if current.startswith(indent) else current.strip())
            self.index += 1
        self.unit("\n".join(lines), first_prefix=indent, prefix=indent, suffix=self.ending(self.index - 1))
