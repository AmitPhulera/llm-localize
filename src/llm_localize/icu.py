"""ICU MessageFormat: parsing messages.

ICU messages, used by FormatJS (react-intl), next-intl, Angular and
others, pick text by argument: ``{count, plural, one {# file} other {#
files}}``.
"""
import re

# An argument that chooses between cases, e.g. "{count, plural," or "{g, select,"
CHOICE_RE = re.compile(r"\{\s*[^{},\s]+\s*,\s*(?:plural|select|selectordinal)\s*,")
# Deeper than any real message, and shallow enough that parsing and checking stay within Python's recursion limit
MAX_DEPTH = 20


class ICUSyntaxError(ValueError):
    pass


class Argument:
    """A ``{name}`` or ``{name, type, style}`` argument."""

    def __init__(self, name, type_="", style=""):
        self.name, self.type, self.style = name, type_, style

    def render(self):
        return "{" + ", ".join(part for part in (self.name, self.type, self.style) if part) + "}"


class Choice:
    """A ``plural``, ``selectordinal`` or ``select`` argument and its cases."""

    def __init__(self, name, type_, cases, offset=""):
        self.name, self.type, self.cases, self.offset = name, type_, cases, offset

    def render(self):
        return "{" + self.name + "}"


def is_icu_choice(text):
    """Return True if ``text`` has a plural, selectordinal or select argument.

    >>> is_icu_choice("{n, plural, one {# file} other {# files}}"), is_icu_choice("Hi {name}")
    (True, False)
    """
    return bool(CHOICE_RE.search(text))


def parse(text):
    """Parse an ICU message into a list of strings, ``Argument`` and ``Choice`` nodes.

    >>> [type(node).__name__ for node in parse("Hi {name}, {n, plural, one {# file} other {# files}}")]
    ['str', 'Argument', 'str', 'Choice']
    """
    parser = _Parser(text)
    nodes = parser.message(in_plural=False)
    if parser.pos != len(text):
        raise ICUSyntaxError(f"unexpected '}}' at {parser.pos}")
    return nodes


class _Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.depth = 0  # how many choices the parser is inside

    def message(self, in_plural):
        nodes, buffer = [], []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "}":
                break
            if char == "{":
                if buffer:
                    nodes.append("".join(buffer))
                    buffer = []
                nodes.append(self.argument(in_plural))
            else:
                buffer.append(char)
                self.pos += 1
        if buffer:
            nodes.append("".join(buffer))
        return nodes

    def argument(self, in_plural):
        self.pos += 1  # {
        name = self.token()
        if not name:
            raise ICUSyntaxError(f"argument without a name at {self.pos}")
        if self.peek() == "}":
            self.pos += 1
            return Argument(name)
        self.expect(",")
        type_ = self.token()
        if type_ in ("plural", "selectordinal", "select"):
            self.expect(",")
            return self.choice(name, type_, in_plural)
        style = ""
        if self.peek() == ",":
            self.pos += 1
            style = self.style()
        self.expect("}")
        return Argument(name, type_, style)

    def choice(self, name, type_, in_plural):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ICUSyntaxError(f"choices nested more than {MAX_DEPTH} deep")
        offset = ""
        self.skip_space()
        if type_ != "select" and self.text.startswith("offset:", self.pos):
            self.pos += len("offset:")
            offset = self.token()
        cases = {}
        while self.peek() != "}":
            key = self.token()
            if not key:
                raise ICUSyntaxError(f"case without a key in {name!r}")
            if key in cases:
                raise ICUSyntaxError(f"case {key!r} repeated in {name!r}")
            self.expect("{")
            cases[key] = self.message(in_plural=in_plural or type_ != "select")
            self.expect("}")
        self.pos += 1
        if "other" not in cases:
            raise ICUSyntaxError(f"{name!r} has no 'other' case")
        self.depth -= 1
        return Choice(name, type_, cases, offset)

    def style(self):
        """Read a style like ``::currency/EUR``, which may hold quoted text but no braces."""
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in "{}":
            self.pos += 1
        return self.text[start:self.pos].strip()

    def token(self):
        self.skip_space()
        match = re.compile(r"[^\s{},]+").match(self.text, self.pos)
        if not match:
            return ""
        self.pos = match.end()
        return match.group()

    def peek(self):
        self.skip_space()
        if self.pos >= len(self.text):
            raise ICUSyntaxError("message ends inside an argument")
        return self.text[self.pos]

    def expect(self, char):
        if self.peek() != char:
            raise ICUSyntaxError(f"expected {char!r} at {self.pos}")
        self.pos += 1

    def skip_space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
