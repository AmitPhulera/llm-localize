"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/en/guide.md``.

The document is split into blocks: headings and paragraphs. Each block
is one message, sent with the headings above it as context.
"""
import re

# A heading line; its closing #s, if any, are split off by _heading_parts, which a regex would do in quadratic time
HEADING_RE = re.compile(r"^( {0,3}#{1,6}[ \t]+)(.*)$")


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


def _heading_parts(match):
    """Return a heading line's ``(prefix, title, closing)``: the closing #s, with the spaces before them, or None.

    >>> _heading_parts(HEADING_RE.match("## Install ##  ")), _heading_parts(HEADING_RE.match("# C#"))
    (('## ', 'Install', ' ##  '), ('# ', 'C#', None))
    """
    prefix, title = match.groups()
    body = title.rstrip(" \t")
    without = body.rstrip("#")
    if without != body and without[-1:] in (" ", "\t"):
        text = without.rstrip(" \t")
        return prefix, text, title[len(text):]
    return prefix, title, None


def _parse(text):
    """Split a Markdown document into literal strings and ``_Unit`` blocks, which join back into it.

    >>> pieces = _parse("# Title\\n\\nSome *text*.\\n")
    >>> [(piece.text, piece.context) if isinstance(piece, _Unit) else piece for piece in pieces]
    [('Title', ''), '\\n', ('Some *text*.', 'Section: Title')]
    """
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.pieces = []
        self.headings = []
        self.index = 0

    def unit(self, text, first_prefix="", prefix="", suffix="", context=None):
        if not text.strip():
            self.pieces.append(first_prefix + text + suffix)
            return
        if context is None:
            context = self.context()
        self.pieces.append(_Unit(str(len(self.pieces)), text, first_prefix, prefix, suffix, context))

    def context(self):
        return "Section: " + " > ".join(title for _, title in self.headings) if self.headings else ""

    def heading(self, level, title):
        """Record a heading, and return its context: the headings it's under."""
        self.headings = [(lvl, t) for lvl, t in self.headings if lvl < level]
        context = self.context()
        self.headings.append((level, title.strip()))
        return context

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
            elif HEADING_RE.match(line):
                self.atx_heading()
            else:
                self.paragraph()
        return self.pieces

    def atx_heading(self):
        prefix, title, closing = _heading_parts(HEADING_RE.match(self.line()))
        level = prefix.count("#")
        context = self.heading(level, title)
        self.unit(title, first_prefix=prefix, suffix=(closing or "") + self.ending(self.index), context=context)
        self.index += 1

    def paragraph(self):
        indent = re.match(r"[ \t]*", self.line()).group()
        lines = []
        while self.index < len(self.lines):
            current = self.line()
            if not current.strip() or (lines and HEADING_RE.match(current)):
                break
            lines.append(current[len(indent):] if current.startswith(indent) else current.strip())
            self.index += 1
        self.unit("\n".join(lines), first_prefix=indent, prefix=indent, suffix=self.ending(self.index - 1))
