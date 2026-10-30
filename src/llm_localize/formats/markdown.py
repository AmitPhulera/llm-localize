"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/guide.md``.

The document is split into blocks: headings and paragraphs. Each block
is one message, sent with the headings above it as context. Every run
translates the whole document, since a changed source can't be matched
to the old translation block by block.
"""
import re
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.units import TranslationUnit

# A heading line; its closing #s, if any, are split off by _heading_parts, which a regex would do in quadratic time
HEADING_RE = re.compile(r"^( {0,3}#{1,6}[ \t]+)(.*)$")


class _Unit:
    """A translatable block, and how to write its translation back: a prefix per line, and the line ending."""

    def __init__(self, key, text, first_prefix="", prefix="", suffix="", context=""):
        self.key, self.text, self.context = key, text, context
        self.first_prefix, self.prefix, self.suffix = first_prefix, prefix, suffix

    def render(self, translation):
        lines = translation.split("\n")
        # Lines end as the block's last one does, so a document with \r\n line endings keeps them
        newline = "\r\n" if self.suffix.endswith("\r\n") else "\n"
        return self.first_prefix + newline.join(
            lines[:1] + [self.prefix + line if line else self.prefix.rstrip() for line in lines[1:]]
        ) + self.suffix


class MarkdownFile(MonolingualFile):
    name = "markdown"
    extensions = (".md", ".markdown")

    def source_path_candidates(self):
        yield from super().source_path_candidates()
        # Also without the language: docs/fr/guide.md and guide.fr.md from docs/guide.md and guide.md
        if self.path_without_language():
            yield self.path_without_language()

    @cached_property
    def _parser(self):
        return _read(self.source_path)

    @property
    def _document(self):
        return self._parser.pieces

    def read_messages(self, path):
        return {piece.key: Message(text=piece.text, context=piece.context)
                for piece in _read(path).pieces if isinstance(piece, _Unit)}

    def untranslated_units(self):
        # The source file itself has nothing to translate, and writing a copy over it would destroy it
        if self.is_source:
            return []
        # Every block, every run: a target can't be matched block by block to a source that changed
        return [TranslationUnit(key=key, source=message.text, context=message.context)
                for key, message in self.source_messages.items()]

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = translation

    def save(self):
        """Write the translated copy: every block's translation, or its source text if it has none yet."""
        text = "".join(
            piece if isinstance(piece, str) else piece.render(self._applied.get(piece.key, piece.text))
            for piece in self._document
        )
        write_file(self.path, text.encode())


def _read(path):
    # newline="" keeps \r\n line endings, so a translation keeps them too
    with open(path, encoding="utf-8", newline="") as f:
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
        # Only at line endings: splitlines() would also split at characters like U+2028 inside a line
        self.lines = [line for line in re.split(r"(?<=\n)|(?<=\r)(?!\n)", text) if line]
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
