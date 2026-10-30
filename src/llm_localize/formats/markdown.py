"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/guide.md``.

The document is split into blocks: headings, paragraphs, list items,
blockquotes, table cells, and HTML blocks with text. Each block is one
message, sent with the headings above it as context. Code blocks and
comments are copied as they are. Every run translates the whole
document, since a changed source can't be matched to the old translation
block by block.
"""
import re
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.units import TranslationUnit

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# The > markers of quotes inside a quote
NESTED_QUOTES_RE = re.compile(r"^(?: {0,3}>[ \t]?)*")
# A heading line; its closing #s, if any, are split off by _heading_parts, which a regex would do in quadratic time
HEADING_RE = re.compile(r"^( {0,3}#{1,6}[ \t]+)(.*)$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
RULE_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_RE = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?")
QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?")
# Written so spaces can be matched only one way: optional runs of them side by side make a long line of
# spaces quadratic to rule out
TABLE_SEPARATOR_RE = re.compile(r"^[ \t]*(?:\|[ \t]*)?:?-+:?(?:[ \t]*\|[ \t]*:?-+:?)*[ \t]*(?:\|[ \t]*)?$")
# A plain YAML value that needs quoting: one starting with an indicator, or holding ": " or " #"
YAML_UNSAFE_RE = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`\s]|: |\s#|:$|\s$")
# HTML blocks holding code rather than text, copied up to their closing tag
RAW_HTML_RE = re.compile(r"^ {0,3}<(script|pre|style|textarea)(?:[\s>]|$)", re.IGNORECASE)
HTML_BLOCK_RE = re.compile(r"^ {0,3}<(?:[A-Za-z][A-Za-z0-9-]*|/[A-Za-z])[\s/>]")
COMMENT_RE = re.compile(r"^ {0,3}<!--")

BACKTICKS_RE = re.compile(r"`+")
TAG_RE = re.compile(r"<[^<>]+>")


class _Unit:
    """A translatable block, and how to write its translation back: a prefix per line, and the line ending."""

    def __init__(self, key, text, first_prefix="", prefix="", suffix="", context="", encode=None):
        self.key, self.text, self.context = key, text, context
        self.first_prefix, self.prefix, self.suffix = first_prefix, prefix, suffix
        self.encode = encode

    def render(self, translation):
        if self.encode:
            translation = self.encode(translation)
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


def _yaml_decode(value, quote):
    """Return a front matter value's text, from its YAML quoting."""
    if quote == "'":
        return value.replace("''", "'")
    if quote == '"':
        return re.sub(r'\\(["\\])', r"\1", value)
    return value


def _yaml_encode(text, quote):
    """Write text as a YAML value in its original quoting, adding double quotes when plain text needs them.

    >>> _yaml_encode("L'application", "'"), _yaml_encode('Un "titre"', '"'), _yaml_encode("Étapes : 2", "")
    ("'L''application'", '"Un \\\\"titre\\\\""', '"Étapes : 2"')
    """
    if quote == "'":
        return "'" + text.replace("'", "''") + "'"
    if quote == '"' or YAML_UNSAFE_RE.search(text) or not text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _code_span_positions(text):
    r"""Return ``(start, end)`` of each code span: a backtick run, up to the next run as long.

    Found in one pass, as CommonMark pairs runs; a run nothing closes is
    plain text.

    >>> text = "a `x` b ``y`z`` c ``` d"
    >>> [text[start:end] for start, end in _code_span_positions(text)]
    ['`x`', '``y`z``']
    >>> _code_span_positions(r"\`<b>`"), _code_span_positions(r"`C:\`")
    ([], [(0, 5)])
    """
    runs = []  # (where it starts as an opening run, where it starts as a closing one, where it ends)
    for match in BACKTICKS_RE.finditer(text):
        start = match.start()
        # A backslash makes the backtick after it plain text, so an opening run starts after that one.
        # In a code span a backslash is plain text, so a closing run is all of its backticks.
        runs.append((start + _backslashes_before(text, start) % 2, start, match.end()))
    following, closing = {}, [None] * len(runs)
    for index in reversed(range(len(runs))):
        opening, start, end = runs[index]
        closing[index] = following.get(end - opening) if opening < end else None
        following[end - start] = index
    spans, index = [], 0
    while index < len(runs):
        if closing[index] is None:
            index += 1
            continue
        spans.append((runs[index][0], runs[closing[index]][2]))
        index = closing[index] + 1
    return spans


def _backslashes_before(text, index):
    """Return how many backslashes come right before ``index``; an odd number escapes what's there."""
    start = index
    while start and text[start - 1] == "\\":
        start -= 1
    return index - start


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

    def unit(self, text, first_prefix="", prefix="", suffix="", context=None, encode=None):
        if not text.strip():
            self.pieces.append(first_prefix + (encode(text) if encode else text) + suffix)
            return
        if context is None:
            context = self.context()
        self.pieces.append(_Unit(str(len(self.pieces)), text, first_prefix, prefix, suffix, context, encode))

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
            elif COMMENT_RE.match(line):
                self.comment()
            elif HEADING_RE.match(line):
                self.atx_heading()
            elif QUOTE_RE.match(line):
                self.blockquote()
            elif LIST_RE.match(line) and not RULE_RE.match(line):
                self.list_item()
            elif self.line(1) is not None and "|" in line and TABLE_SEPARATOR_RE.match(self.line(1)):
                self.table()
            elif HTML_BLOCK_RE.match(line):
                self.html_block()
            elif line.startswith(("    ", "\t")) and self.is_indented_code(line):
                self.indented_code()
            else:
                self.paragraph()
        return self.pieces

    def comment(self):
        start = self.index
        while self.index < len(self.lines) and "-->" not in self.line():
            self.index += 1
        self.index = min(self.index + 1, len(self.lines))
        self.pieces.append("".join(self.lines[start:self.index]))

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
        """A blockquote: its text as messages, and code inside it, fenced or indented, copied as it is."""
        text, fence = [], None  # the indexes of quoted text lines not yet added, and an open code fence
        while self.index < len(self.lines) and QUOTE_RE.match(self.line() or ""):
            content = self.quoted(self.index)
            # In a quote inside this one too
            innermost = NESTED_QUOTES_RE.sub("", content)
            paragraph_ended = not text or not self.quoted(text[-1]).strip()
            if fence is None and (FENCE_RE.match(innermost)
                                  or (content.startswith(("    ", "\t")) and paragraph_ended)):
                self.quote_text(text)
                text = []
                if FENCE_RE.match(innermost):
                    fence = FENCE_RE.match(innermost).group(1)
                self.literal()
            elif fence is not None:
                closing = innermost.strip()
                if closing.startswith(fence[0] * len(fence)) and not closing.strip(fence[0]):
                    fence = None
                self.literal()
            else:
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

    def table(self):
        while self.index < len(self.lines) and self.line() is not None and "|" in self.line():
            line = self.line()
            if TABLE_SEPARATOR_RE.match(line):
                self.literal()
                continue
            for cell in _split_row(line):
                if isinstance(cell, str):
                    self.pieces.append(cell)
                else:
                    self.unit(cell[1], first_prefix=cell[0], suffix=cell[2])
            self.pieces.append(self.ending(self.index))
            self.index += 1

    def html_block(self):
        start = self.index
        raw = RAW_HTML_RE.match(self.line())
        if raw:
            # Code, like <script> or <pre>, copied up to its closing tag, blank lines and all
            closing = f"</{raw.group(1).lower()}>"
            while self.index < len(self.lines) and closing not in self.line().lower():
                self.index += 1
            self.index = min(self.index + 1, len(self.lines))
            self.pieces.append("".join(self.lines[start:self.index]))
            return
        while self.index < len(self.lines) and self.line().strip():
            self.index += 1
        block = "".join(self.lines[start:self.index])
        if TAG_RE.sub("", block).strip():
            body = block.rstrip("\r\n")
            # Line endings within it go back as the block's last one, as for other blocks
            self.unit(body.replace("\r\n", "\n"), suffix=block[len(body):])
        else:
            self.pieces.append(block)

    def paragraph(self):
        indent = re.match(r"[ \t]*", self.line()).group()
        lines = []
        while self.index < len(self.lines):
            current = self.line()
            if (not current.strip() or (lines and (FENCE_RE.match(current) or HEADING_RE.match(current)
                                                    or QUOTE_RE.match(current) or LIST_RE.match(current)
                                                    or HTML_BLOCK_RE.match(current)
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


def _split_row(line):
    r"""Split a table row into literal pipes and ``(leading space, cell text, trailing space)`` cells.

    Pipes inside code spans or escaped with a backslash don't split cells.
    A code span ends at a run of as many backticks as it starts with, and
    a run nothing closes is plain text.

    >>> _split_row("| a | `x|y` | b\\|c |")
    ['|', (' ', 'a', ' '), '|', (' ', '`x|y`', ' '), '|', (' ', 'b\\|c', ' '), '|']
    >>> _split_row("| ``y|`z`` | ` | b |")
    ['|', (' ', '``y|`z``', ' '), '|', (' ', '`', ' '), '|', (' ', 'b', ' '), '|']
    """
    spans = dict(_code_span_positions(line))
    pieces, cell, index = [], "", 0
    while index < len(line):
        if index in spans:
            cell += line[index:spans[index]]
            index = spans[index]
            continue
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            cell += line[index:index + 2]
            index += 2
            continue
        if char == "|":
            pieces.append(cell)
            pieces.append("|")
            cell = ""
        else:
            cell += char
        index += 1
    pieces.append(cell)
    result = []
    for piece in pieces:
        if piece == "|" or not piece.strip():
            if piece:
                result.append(piece)
            continue
        stripped = piece.strip()
        start = piece.index(stripped)
        result.append((piece[:start], stripped, piece[start + len(stripped):]))
    return result
