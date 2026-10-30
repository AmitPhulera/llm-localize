"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/guide.md``.

The document is split into blocks: headings, paragraphs, list items, and
blockquotes. Each block is one message, sent with the headings above it
as context. Code blocks are copied as they are. Every run translates the
whole document, since a changed source can't be matched to the old
translation block by block.
"""
import re
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.units import TranslationUnit

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A heading line; its closing #s, if any, are split off by _heading_parts, which a regex would do in quadratic time
HEADING_RE = re.compile(r"^( {0,3}#{1,6}[ \t]+)(.*)$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
RULE_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_RE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?")
QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?")


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

    >>> pieces = _parse("# Title\\n\\nSome *text*.\\n\\n```py\\nx = 1\\n```\\n")
    >>> [(piece.text, piece.context) if isinstance(piece, _Unit) else piece for piece in pieces]
    [('Title', ''), '\\n', ('Some *text*.', 'Section: Title'), '\\n', '```py\\nx = 1\\n```\\n']
    """
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text):
        # Only at line endings: splitlines() would also split at characters like U+2028 inside a line
        self.lines = [line for line in re.split(r"(?<=\n)|(?<=\r)(?!\n)", text) if line]
        self.pieces = []
        self.headings = []
        self.index = 0
        self.indent_cache = (0, None)  # pieces looked at by list_content_indent, and its answer

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
            if not line.strip() or RULE_RE.match(line):
                self.literal()
            elif FENCE_RE.match(line) or self.is_list_fence(line):
                self.fence()
            elif HEADING_RE.match(line):
                self.atx_heading()
            elif QUOTE_RE.match(line):
                self.blockquote()
            elif LIST_RE.match(line) and not RULE_RE.match(line):
                self.list_item()
            elif line.startswith(("    ", "\t")) and self.is_indented_code(line):
                self.indented_code()
            else:
                self.paragraph()
        return self.pieces

    def indented_code(self):
        start = self.index
        while self.index < len(self.lines) and (not self.line().strip() or self.line().startswith(("    ", "\t"))):
            self.index += 1
        self.pieces.append("".join(self.lines[start:self.index]))

    def fence(self):
        marker = FENCE_RE.match(self.line().lstrip()).group(1)
        start = self.index
        self.index += 1
        while self.index < len(self.lines):
            current = self.line().strip()
            self.index += 1
            if current.startswith(marker[0] * len(marker)) and not current.strip(marker[0]):
                break
        self.pieces.append("".join(self.lines[start:self.index]))

    def atx_heading(self):
        prefix, title, closing = _heading_parts(HEADING_RE.match(self.line()))
        level = prefix.count("#")
        context = self.heading(level, title)
        self.unit(title, first_prefix=prefix, suffix=(closing or "") + self.ending(self.index), context=context)
        self.index += 1

    def blockquote(self):
        text = []  # the indexes of the quoted lines
        while self.index < len(self.lines) and QUOTE_RE.match(self.line() or ""):
            text.append(self.index)
            self.index += 1
        self.quote_text(text)

    def quoted(self, index):
        """Return a quoted line without its ``>`` marker."""
        line = self.lines[index].rstrip("\r\n")
        return line[QUOTE_RE.match(line).end():]

    def quote_text(self, indexes):
        """Add quoted lines of text as a message, and the blank quoted lines around it as they are."""
        text = [position for position, index in enumerate(indexes) if self.quoted(index).strip()]
        if not text:
            self.pieces.extend(self.lines[index] for index in indexes)
            return
        first, last = text[0], text[-1]
        self.pieces.extend(self.lines[index] for index in indexes[:first])
        prefix = QUOTE_RE.match(self.lines[indexes[first]]).group()
        self.unit("\n".join(self.quoted(index) for index in indexes[first:last + 1]), first_prefix=prefix,
                  prefix=prefix.rstrip() + " ", suffix=self.ending(indexes[last]))
        self.pieces.extend(self.lines[index] for index in indexes[last + 1:])

    def list_item(self):
        match = LIST_RE.match(self.line())
        fence = FENCE_RE.match(self.line()[match.end():])
        if fence:
            # An item that starts with code: copied up to its closing fence, or the item's end
            start, marker_fence = self.index, fence.group(1)
            closing = re.compile(rf"{re.escape(marker_fence[0])}{{{len(marker_fence)},}}[ \t]*$")
            self.index += 1
            while self.index < len(self.lines) and not closing.match(self.line().strip()) and (
                    not self.line().strip() or self.line().startswith(" " * len(match.group()))):
                self.index += 1
            if self.index < len(self.lines) and closing.match(self.line().strip()):
                self.index += 1
            self.pieces.append("".join(self.lines[start:self.index]))
            return
        marker = match.group()
        lines = [self.line()[match.end():]]
        indent = " " * len(marker)
        self.index += 1
        while self.index < len(self.lines):
            current = self.line()
            # A fence may be indented as far as the item's text, and 3 more
            fence = FENCE_RE.match(current.lstrip()) and len(current) - len(current.lstrip()) <= len(marker) + 3
            # A rule ends the item too: it can't underline the item's text, as "---" would once indented
            if (not current.strip() or LIST_RE.match(current) or fence or RULE_RE.match(current)
                    or HEADING_RE.match(current) or QUOTE_RE.match(current)):
                break
            # Only the indent: two trailing spaces are a line break
            lines.append(current.lstrip())
            self.index += 1
        self.unit("\n".join(lines), first_prefix=marker, prefix=indent, suffix=self.ending(self.index - 1))

    def is_list_fence(self, line):
        """True if a line opens a code fence inside the list item above: indented at most 3 past its text."""
        content = self.list_content_indent()
        stripped = line.lstrip(" ")
        return content is not None and len(line) - len(stripped) <= content + 3 and bool(FENCE_RE.match(stripped))

    def is_indented_code(self, line):
        """True if an indented line starts a code block: four columns in, or past a list item's text."""
        content = self.list_content_indent()
        expanded = line.expandtabs(4)
        return content is None or len(expanded) - len(expanded.lstrip()) >= content + 4

    def list_content_indent(self):
        """Return how far in the text of the list item above starts, if the blocks since belong to it, or None.

        Pieces are only ever added, so the answer for the pieces looked at
        last time is kept, and only those added since are looked at.
        """
        looked_at, indent = self.indent_cache
        self.indent_cache = (len(self.pieces), self._list_content_indent(looked_at, indent))
        return self.indent_cache[1]

    def _list_content_indent(self, looked_at, indent):
        for piece in reversed(self.pieces[looked_at:]):
            if isinstance(piece, str):
                # Blank lines, and code indented inside the item
                if not piece.strip() or piece.startswith(("    ", "\t")):
                    continue
                return None
            if LIST_RE.match(piece.first_prefix):
                return len(piece.first_prefix.expandtabs(4))
            # A paragraph indented to continue the item
            if piece.first_prefix and not piece.first_prefix.strip():
                continue
            return None
        return indent

    def paragraph(self):
        indent = re.match(r"[ \t]*", self.line()).group()
        lines = []
        while self.index < len(self.lines):
            current = self.line()
            if (not current.strip() or (lines and (FENCE_RE.match(current) or HEADING_RE.match(current)
                                                    or QUOTE_RE.match(current) or LIST_RE.match(current)
                                                    or self.is_list_fence(current)))):
                break
            if lines and SETEXT_RE.match(current):
                # The paragraph was a heading, underlined
                text = "\n".join(lines)
                context = self.heading(1 if current.strip().startswith("=") else 2, text)
                self.unit(text, first_prefix=indent, prefix=indent, suffix=self.ending(self.index - 1),
                          context=context)
                self.literal()
                return
            lines.append(current[len(indent):] if current.startswith(indent) else current.strip())
            self.index += 1
        self.unit("\n".join(lines), first_prefix=indent, prefix=indent, suffix=self.ending(self.index - 1))
