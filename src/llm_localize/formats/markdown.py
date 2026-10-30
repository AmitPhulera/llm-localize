"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/guide.md``.

The document is split into blocks: headings, paragraphs, list items,
blockquotes, table cells, and HTML blocks with text. Each block is one
message, sent with the headings above it as context. Code blocks,
front matter (except ``title`` and ``description``), link reference
definitions and comments are copied as they are. Every run translates
the whole document, since a changed source can't be matched to the old
translation block by block.
"""
import bisect
import re
from collections import Counter
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.units import TranslationUnit

FRONT_MATTER_KEYS = ("title", "description")

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
# Its destination may be on the next line
LINK_DEFINITION_RE = re.compile(r"^ {0,3}\[((?:\\.|[^\\\]])+)\]:")
# A definition's destination, with an optional title, or the start of one that goes on to the next line
DESTINATION = r"(?:<[^<>\n]*>|\S+)"
DESTINATION_RE = re.compile(rf"""^[ \t]*({DESTINATION})(?:[ \t]+(?:"[^"]*"?|'[^']*'?|\([^)]*\)?))?[ \t]*$""")
FOOTNOTE_RE = re.compile(r"^( {0,3}\[\^[^\]]+\]:[ \t]*)(.*)$")
# YAML double-quoted escapes, and how control characters are written in them
YAML_ESCAPE_RE = re.compile(r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")
YAML_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
                "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
                "L": "\u2028", "P": "\u2029"}
YAML_CONTROL_ESCAPES = {"\t": "\\t", "\n": "\\n", "\r": "\\r", "\0": "\\0"}
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")
# A block scalar's indicator, like | or >-, whose value is on the indented lines below
YAML_BLOCK_RE = re.compile(r"[|>][+-]?\d?[+-]?")
# A plain YAML value that needs quoting: one starting with an indicator, or holding ": " or " #"
YAML_UNSAFE_RE = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`\s]|: |\s#|:$|\s$")
# HTML blocks holding code rather than text, copied up to their closing tag
RAW_HTML_RE = re.compile(r"^ {0,3}<(script|pre|style|textarea)(?:[\s>]|$)", re.IGNORECASE)
HTML_BLOCK_RE = re.compile(r"^ {0,3}<(?:[A-Za-z][A-Za-z0-9-]*|/[A-Za-z])[\s/>]")
COMMENT_RE = re.compile(r"^ {0,3}<!--")
# A front matter key, before its value, like title: "Guide" # shown in the nav
FRONT_MATTER_KEY_RE = re.compile(rf"^({'|'.join(FRONT_MATTER_KEYS)})([ \t]*:[ \t]*)")
FRONT_MATTER_COMMENT_RE = re.compile(r"[ \t]+#")


BACKTICKS_RE = re.compile(r"`+")
# Blockquote and list markers before a line's content, like "> " or "- "
CONTAINER_MARKERS_RE = re.compile(r"^(?:[ \t]*(?:>|[-*+]|\d{1,9}[.)])(?=[ \t]|$)[ \t]?)*")
# Plain YAML values a loader reads as something else, like a boolean or a number
YAML_IMPLICIT_RE = re.compile(r"(?i)~|null|true|false|yes|no|on|off|y|n|[-+]?\.?(?:inf|nan)"
                              r"|[-+]?(?:\d[\d_]*(?:\.[\d_]*)?|\.\d+)(?:e[-+]?\d+)?|0[box][\da-f_]+"
                              r"|\d{4}-\d\d?-\d\d?(?:[ tT].*)?")
LINK_LABEL_RE = re.compile(r"\]\[([^\]]*)\]|\[\^([^\]]+)\]")
TAG_RE = re.compile(r"<[^<>]+>")
NON_SPACE_RE = re.compile(r"\S")
# A backslash-escaped bracket or <, after any escaped backslashes; a < with the tag name after it, so an
# escape can't move from one tag to another
ESCAPE_RE = re.compile(r"(?<!\\)(?:\\\\)*\\([\[\]]|<[/!?]?[A-Za-z][\w:.-]*|<)")


class _Unit:
    """A translatable block, and how to write its translation back: a prefix per line, and the line ending."""

    def __init__(self, key, text, first_prefix="", prefix="", suffix="", context="", encode=None):
        self.key, self.text, self.context = key, text, context
        self.first_prefix, self.prefix, self.suffix = first_prefix, prefix, suffix
        self.encode = encode

    def render(self, translation):
        if self.encode:
            translation = self.encode(translation)
        # Split as the document's lines are, so a \r can't start a line without the block's prefix
        lines = re.split(r"\r\n?|\n", translation)
        # Lines end as the block's last one does, so a document with \r\n line endings keeps them
        newline = "\r\n" if self.suffix.endswith("\r\n") else "\n"
        return self.first_prefix + newline.join(
            lines[:1] + [self.prefix + line if line else self.prefix.rstrip() for line in lines[1:]]
        ) + self.suffix


class MarkdownFile(MonolingualFile):
    name = "markdown"
    extensions = (".md", ".markdown")
    instructions = (
        "Messages are blocks of a Markdown document, with the headings above them as context. Keep the "
        "Markdown syntax: emphasis markers, `inline code` (never translate inside backticks), link and "
        "image targets in (...), reference labels in [...], footnote markers like [^1], and HTML tags. "
        "Translate link text and image alt text, but not text in [...] that's a reference to a link defined "
        "elsewhere. Keep reference labels and footnote markers in the order they come in the source, "
        "rewording the sentence if needed, since each one is checked against its position. Keep line breaks "
        "within a block."
    )

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

    def find_problem(self, source, translation):
        source_spans, source_text = _split_code(source)
        translation_spans, translation_text = _split_code(translation)
        if Counter(source_spans) != Counter(translation_spans):
            return "inline code"
        # Without its backslash, an escaped \[ or \< would start a link or a tag
        if Counter(ESCAPE_RE.findall(source_text)) != Counter(ESCAPE_RE.findall(translation_text)):
            return "escapes"
        if Counter(_link_targets(source_text)) != Counter(_link_targets(translation_text)):
            return "links"
        # In order, so [one][a] and [two][b] can't become [un][b] and [deux][a]
        if LINK_LABEL_RE.findall(source_text) != LINK_LABEL_RE.findall(translation_text):
            return "links"
        # [label] alone links to the definition [label]: url, so its text can't change. In
        # [text][label] and [text](url), the first brackets are only link text.
        for label in self._parser.labels:
            pattern = re.compile(rf"(?<!\])\[{re.escape(label)}\](?![\[(:])", re.IGNORECASE)
            if len(pattern.findall(source_text)) != len(pattern.findall(translation_text)):
                return "links"
        # A table cell or a heading's title is written on its one line, where "# of users" is text
        if source in self._parser.inline_texts and source not in self._parser.block_texts:
            return super().find_problem(source_text, translation_text)
        source_lines, translation_lines = _without_containers(source_text), _without_containers(translation_text)
        # A fence added in a block would make the rest of the document code
        if _fences(translation_lines) != _fences(source_lines):
            return "code blocks"
        if _headings(translation_lines) != _headings(source_lines):
            return "headings"
        return super().find_problem(source_text, translation_text)

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


def _front_matter_line(line):
    r"""Return a front matter line's ``(key, separator, quote, value, comment)``, or None for another key.

    The value ends at its closing quote, or unquoted at a comment, followed
    only by a comment or spaces.

    >>> _front_matter_line('title: "Guide" # shown'), _front_matter_line("title: A  B  ")
    (('title', ': ', '"', 'Guide', ' # shown'), ('title', ': ', '', 'A  B', '  '))
    >>> _front_matter_line(r'title: "Use \" # to" # note'), _front_matter_line("title: 'It''s' # x")
    (('title', ': ', '"', 'Use \\" # to', ' # note'), ('title', ': ', "'", "It''s", ' # x'))
    """
    key = FRONT_MATTER_KEY_RE.match(line)
    if not key:
        return None
    rest = line[key.end():]
    if rest[:1] in ("'", '"'):
        quote, index, last = rest[0], 1, len(rest.rstrip(" \t"))
        while index < len(rest):
            # A double-quoted value may escape a quote with \, a single-quoted one by doubling it
            if quote == '"' and rest[index] == "\\" or rest.startswith("''", index) and quote == "'":
                index += 2
                continue
            if rest[index] == quote:
                if index + 1 >= last or FRONT_MATTER_COMMENT_RE.match(rest, index + 1):
                    return key.group(1), key.group(2), quote, rest[1:index], rest[index + 1:]
                break
            index += 1
        else:
            # Not closed on this line: the value goes on, so it isn't one to translate here
            return None
    # Before the spaces that end it, or that come before a #
    # One space and #, not FRONT_MATTER_COMMENT_RE: a search for a run of them rescans a long run of spaces
    comment = re.search(r"[ \t]#", rest)
    end = len((rest[:comment.start()] if comment else rest).rstrip(" \t"))
    return key.group(1), key.group(2), "", rest[:end], rest[end:]


def _yaml_decode(value, quote):
    r"""Return a front matter value's text, from its YAML quoting.

    >>> _yaml_decode(r"Line\nBreak \t \"tab\" \u00e9", '"'), _yaml_decode("L''app", "'")
    ('Line\nBreak \t "tab" é', "L'app")
    """
    if quote == "'":
        return value.replace("''", "'")
    if quote == '"':
        return YAML_ESCAPE_RE.sub(_yaml_unescape, value)
    return value


def _yaml_unescape(match):
    escape = match.group(1)
    if escape[0] in "xuU":
        code = int(escape[1:], 16)
        # One that names no character is left as written
        return match.group() if code > 0x10FFFF else chr(code)
    return YAML_ESCAPES.get(escape, escape)


def _yaml_encode(text, quote):
    r"""Write text as a YAML value in its original quoting, adding double quotes when plain text needs them.

    Line breaks and other control characters are written as escapes in
    double quotes, so a value stays on its line and can't add keys.

    >>> _yaml_encode("L'application", "'"), _yaml_encode('Un "titre"', '"'), _yaml_encode("Étapes : 2", "")
    ("'L''application'", '"Un \\"titre\\""', '"Étapes : 2"')
    >>> print(_yaml_encode("Bonjour\nfoo: bar", ""), _yaml_encode("Line\tbreak", "'"))
    "Bonjour\nfoo: bar" "Line\tbreak"
    """
    control = CONTROL_RE.search(text)
    if quote == "'" and not control:
        return "'" + text.replace("'", "''") + "'"
    if quote or control or YAML_UNSAFE_RE.search(text) or YAML_IMPLICIT_RE.fullmatch(text) or not text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + CONTROL_RE.sub(_yaml_control_escape, escaped) + '"'
    return text


def _yaml_control_escape(match):
    character = match.group()
    return YAML_CONTROL_ESCAPES.get(character) or (
        f"\\x{ord(character):02x}" if ord(character) < 0x100 else f"\\u{ord(character):04x}")


def _link_targets(text):
    r"""Return the destination of each inline link and image, allowing balanced parentheses in it.

    One inside a link's destination or title isn't a link of its own, but one
    after brackets that only look like a link, as in ``[a](b [c](d))``, is.

    >>> _link_targets('[a](docs/a_(b).md "Title") and ![x](<my img.png>)')
    ['docs/a_(b).md', '<my img.png>']
    >>> _link_targets('[a](b [c](//evil.example))'), _link_targets('[a](b "[c](d)")')
    (['\x00b', '//evil.example'], ['b'])

    Text that only looks like one, as after an escaped ``\[``, is counted
    too, marked, so a translation can't make it a link by moving the escape.

    >>> _link_targets(r'\[a](b) [c]'), _link_targets(r'[a](b) \[c]')
    (['\x00b'], ['b'])
    >>> _link_targets('[a [b](c)](d)'), _link_targets('![a [b](c)](d)')
    (['c', '\x00d'], ['c', 'd'])
    """
    if "](" not in text:
        return []
    # The [ each ] closes; an escaped one is text, and a ] with no [ before it doesn't end link text
    opened, closing = [], {}
    for bracket in re.finditer(r"[\[\]]", text):
        if _backslashes_before(text, bracket.start()) % 2:
            continue
        if bracket.group() == "[":
            opened.append(bracket.start())
        elif opened:
            closing[bracket.start()] = opened.pop()
    ends = _closing_parentheses(text)
    # Where each whitespace and each character that can end a destination or title is, found by bisecting,
    # so no link is scanned again from each one inside it
    # A line break after a backslash may be part of a destination, as some renderers have it
    spaces = [match.start() for match in re.finditer(r"\s", text)
              if match.group() != "\n" or not _backslashes_before(text, match.start()) % 2]
    pointy_breaks = [match.start() for match in re.finditer(r"[\n<]", text)
                     if match.group() == "\n" or not _backslashes_before(text, match.start()) % 2]
    # An escaped one doesn't end a title: [a](b "\")") is one link
    closers = {char: [match.start() for match in re.finditer(re.escape(char), text)
                      if not _backslashes_before(text, match.start()) % 2] for char in "\"'()>"}

    def first(positions, start, stop):
        found = bisect.bisect_left(positions, start)
        return positions[found] if found < len(positions) and positions[found] < stop else None

    non_spaces = {}

    def skip_spaces(index, stop):
        # Remembered, so a run of spaces many candidates share is only crossed once
        if index not in non_spaces:
            found = NON_SPACE_RE.search(text, index)
            non_spaces[index] = found.start() if found else len(text)
        return min(non_spaces[index], stop)

    # Where each real link's ]( is: a link can't hold another in its text, though an image can
    links = []

    def holds_a_link(bracket):
        opener = closing[bracket]
        image = opener and text[opener - 1] == "!" and not _backslashes_before(text, opener - 1) % 2
        return not image and bisect.bisect_left(links, opener) < len(links)

    # Where each real link's destination starts and its ")" is: a [ there opens no link text
    destinations = []

    def in_a_destination(opener):
        found = bisect.bisect_right(destinations, (opener, len(text))) - 1
        return found >= 0 and opener <= destinations[found][1]

    targets, covered = [], 0
    for match in re.finditer(r"\]\(", text):
        if match.start() < covered:
            continue
        close = ends[match.end()]
        start = skip_spaces(match.end(), len(text))
        if text.startswith("<", start):
            # <...> holds no line break or other <, and parentheses in it needn't balance, so the link's ")"
            # is the first unbalanced one after it
            bracket = first(closers[">"], start, len(text))
            if bracket is None or first(pointy_breaks, start + 1, bracket) is not None:
                # Not a destination, and nothing else starting with < is
                targets.append("\0" + text[start:start + 2048])
                continue
            end = bracket + 1
            close = ends[end]
        else:
            start = min(start, close)
            space = first(spaces, start, close)
            end = space if space is not None else close
        if close >= len(text):
            # Never closed, so not a link
            continue
        # A link if only a title, in quotes or parentheses, comes between its destination and its ")"
        after = skip_spaces(end, close)
        opened_here = (match.start() in closing and not holds_a_link(match.start())
                       and not in_a_destination(closing[match.start()]))
        real = after == close < len(text) and opened_here
        if not real and opened_here and after > end and text[after] in "\"'(":
            # Its ")" comes after the title, which may hold one, as in [a](b "c)d")
            title_end = first(closers[")" if text[after] == "(" else text[after]], after + 1, len(text))
            # One in parentheses can't hold another (, so ([c](d)) is no title, and [c](d) a link
            if text[after] == "(" and first(closers["("], after + 1, title_end or len(text)) is not None:
                title_end = None
            title_close = len(text) if title_end is None else skip_spaces(title_end + 1, len(text))
            real = text.startswith(")", title_close)
            close = title_close if real else close
        if real:
            covered = close
            links.append(match.start())
            destinations.append((match.end(), close))
            targets.append(text[start:end])
        else:
            # Not a link, but counted the same way in both texts, at a bounded cost
            targets.append("\0" + text[start:min(end, start + 2048)])
    return targets


def _closing_parentheses(text):
    """Return, for each position, where the parentheses opened before it close: the first ``)`` that
    brings the depth below what it was there, or the end of the text.

    Worked out for every position in one pass, so finding each link's end
    doesn't rescan the rest of the block. A backslash escapes the next
    character.

    >>> text = "see](a(b)c) and](d)"
    >>> ends = _closing_parentheses(text)
    >>> text[5:ends[5]], text[17:ends[17]]
    ('a(b)c', 'd')
    """
    depths, depth, escaped = [0], 0, False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            depth += (char == "(") - (char == ")")
        depths.append(depth)
    ends, lower = [len(text)] * (len(text) + 1), []
    for position in reversed(range(len(text) + 1)):
        # The nearest later position whose depth is lower: the ) before it closed this one's parentheses
        while lower and depths[lower[-1]] >= depths[position]:
            lower.pop()
        if lower:
            ends[position] = lower[-1] - 1
        lower.append(position)
    return ends


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


def _split_code(text):
    """Return ``(code spans, text)``: the spans, and the text with each blanked out, so placeholders and links
    inside them aren't checked.

    >>> _split_code("Run `ls` or `dir`.")
    (['`ls`', '`dir`'], 'Run `` or ``.')
    """
    spans, pieces, previous = [], [], 0
    for start, end in _code_span_positions(text):
        spans.append(text[start:end])
        pieces.append(text[previous:start] + "``")
        previous = end
    return spans, "".join(pieces) + text[previous:]


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


def _without_containers(text):
    """Return a block's text with each line's quote and list markers taken off, for the checks below."""
    return "\n".join(CONTAINER_MARKERS_RE.sub("", line) for line in text.splitlines())


def _fences(lines):
    """Return how many of a block's lines, without containers, open or close a fenced code block."""
    return sum(bool(FENCE_RE.match(line)) for line in lines.splitlines())


def _headings(lines):
    """Return how many of a block's lines, without containers, are headings, or make the line above one."""
    return sum(bool(HEADING_RE.match(line) or SETEXT_RE.match(line)) for line in lines.splitlines())


def _definition(line, following):
    """True if ``line`` starts a link reference definition: its destination after it or on ``following``."""
    definition = LINK_DEFINITION_RE.match(line)
    if not definition:
        return False
    rest = line[definition.end():]
    return bool(DESTINATION_RE.match(rest if rest.strip() else following))


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
        self.labels = set()
        # The texts of blocks written on one line, table cells and headings, and of the rest
        self.inline_texts, self.block_texts = set(), set()
        self.index = 0
        self.indent_cache = (0, None)  # pieces looked at by list_content_indent, and its answer

    def unit(self, text, first_prefix="", prefix="", suffix="", context=None, encode=None, one_line=False):
        """Add a block to translate; ``one_line`` if it's written on one line, like a heading's title."""
        (self.inline_texts if one_line else self.block_texts).add(text)
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

    def definition_lines(self):
        """Return how many lines the definition here takes: its destination may be on the next line, and its
        title on the line after or over several."""
        rest = self.line()[LINK_DEFINITION_RE.match(self.line()).end():]
        count = 1
        if not rest.strip():
            rest, count = self.line(1), 2
        title = re.match(rf"""[ \t]*{DESTINATION}[ \t]+(["'(])""", rest)
        if not title and self.line(count):
            # On the next line
            title = re.match(r"""[ \t]*(["'(])""", self.line(count))
            rest, count = (self.line(count), count + 1) if title else (rest, count)
        if title:
            # Up to the line that closes it; a title can't hold a blank line
            closing = ")" if title.group(1) == "(" else title.group(1)
            if closing not in rest[title.end():]:
                while self.line(count) and closing not in self.line(count):
                    count += 1
                count += self.line(count) is not None and closing in self.line(count)
        return count

    def literal(self, count=1):
        self.pieces.append("".join(self.lines[self.index:self.index + count]))
        self.index += count

    def parse(self):
        if self.lines and self.lines[0].startswith("\ufeff"):
            # A byte order mark, kept as it is, before front matter that follows it
            self.pieces.append("\ufeff")
            self.lines[0] = self.lines[0][1:]
        self.front_matter()
        while self.index < len(self.lines):
            line = self.line()
            if FOOTNOTE_RE.match(line):
                self.footnote()
            elif _definition(line, self.lines[self.index + 1] if self.index + 1 < len(self.lines) else ""):
                self.labels.add(line.strip()[1:line.strip().index("]")].lower())
                self.literal(self.definition_lines())
            elif not line.strip() or RULE_RE.match(line):
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

    def front_matter(self):
        if self.line() not in ("---", "+++"):
            return
        fence = self.line()
        end = next((index for index in range(1, len(self.lines)) if self.lines[index].rstrip("\r\n") == fence),
                   None)
        if end is None:
            return
        self.literal()
        while self.index < end:
            match = _front_matter_line(self.line())
            # A block scalar (title: |) or a value going on over indented lines is copied: its text
            # isn't all on this line
            continued = self.index + 1 < end and self.line(1)[:1] in (" ", "\t") and self.line(1).strip()
            key, separator, quote, value, comment = match or (None,) * 5
            block_scalar = not quote and YAML_BLOCK_RE.fullmatch((value or "").strip())
            if match and value.strip() and not continued and not block_scalar:
                text = _yaml_decode(value, quote)
                # An unchanged value is written as it was, escapes and all
                self.unit(text, first_prefix=key + separator, suffix=comment + self.ending(self.index),
                          context=f"Front matter: {key}",
                          encode=lambda new, text=text, raw=quote + value + quote, quote=quote:
                              raw if new == text else _yaml_encode(new, quote))
                self.index += 1
            else:
                self.literal()
        self.literal()

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
        self.unit(title, first_prefix=prefix, suffix=(closing or "") + self.ending(self.index), context=context,
                  encode=_one_line, one_line=True)
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

    def footnote(self):
        """A footnote definition, ``[^1]: text``, and the indented lines continuing it."""
        prefix, text = FOOTNOTE_RE.match(self.line()).groups()
        lines = [text]
        self.index += 1
        while self.index < len(self.lines) and self.line().strip() and self.line().startswith((" ", "\t")):
            lines.append(self.line().lstrip())
            self.index += 1
        self.unit("\n".join(lines), first_prefix=prefix, prefix="    ", suffix=self.ending(self.index - 1))

    def table(self):
        while self.index < len(self.lines) and self.line() is not None and "|" in self.line():
            line = self.line()
            if TABLE_SEPARATOR_RE.match(line):
                self.literal()
                continue
            # A row's first cell starts its line when the row has no leading pipe
            starts_line = not line.lstrip().startswith("|")
            for cell in _split_row(line):
                if isinstance(cell, str):
                    self.pieces.append(cell)
                else:
                    self.unit(cell[1], first_prefix=cell[0], suffix=cell[2],
                              encode=_first_table_cell if starts_line else _table_cell, one_line=True)
                    starts_line = False
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


def _one_line(text):
    """Join a translation's lines, for a block that must stay on one line, like a heading."""
    return re.sub(r"\r\n?|\n", " ", text)


def _first_table_cell(text):
    r"""Write a translated cell that starts its line so it can't start a block, like a list or a fence, either.

    >>> print(_first_table_cell("1."), _first_table_cell("# of users"), _first_table_cell("```"))
    1\. \# of users \```
    >>> print(_first_table_cell("`--force`"), _first_table_cell("**Bold**"), _first_table_cell("1st"))
    `--force` **Bold** 1st
    """
    text = _table_cell(text)
    # Only what would start a block: inline code, emphasis or ~~strike~~ at the start stays as it is. A
    # backtick fence can't have a backtick after it, so ```` ```js ```` is a code span.
    text = re.sub(r"^(\s*)(?=#{1,6}(?:[ \t]|$)|>|[-+*](?:[ \t]|$)|`{3,}(?![^`]*`)|~{3,})", r"\1\\", text)
    return re.sub(r"^(\s*)(\d{1,9})([.)])(?=[ \t]|$)", r"\1\2\\\3", text)


def _table_cell(text):
    r"""Write a translated table cell so it stays one cell: pipes escaped, except in code, and on one line.

    >>> print(_table_cell("x | y `a|b` c\\|d\nnext"))
    x \| y `a|b` c\|d next
    """
    parts = re.split(r"(`+.+?`+)", _one_line(text))
    return "".join(part if index % 2 else re.sub(r"(?<!\\)\|", r"\\|", part) for index, part in enumerate(parts))


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
