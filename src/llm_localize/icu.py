"""ICU MessageFormat: parsing messages.

ICU messages, used by FormatJS (react-intl), next-intl, Angular and
others, pick text by argument: ``{count, plural, one {# file} other {#
files}}``.
"""
import re

# An argument that chooses between cases, e.g. "{count, plural," or "{g, select,"
CHOICE_RE = re.compile(r"\{\s*[^{},\s]+\s*,\s*(?:plural|select|selectordinal)\s*,")


class ICUSyntaxError(ValueError):
    pass


class Argument:
    """A ``{name}`` or ``{name, type, style}`` argument."""

    def __init__(self, name, type_="", style=""):
        self.name, self.type, self.style = name, type_, style

    def render(self):
        return "{" + ", ".join(part for part in (self.name, self.type, self.style) if part) + "}"


def is_icu_choice(text):
    """Return True if ``text`` has a plural, selectordinal or select argument.

    >>> is_icu_choice("{n, plural, one {# file} other {# files}}"), is_icu_choice("Hi {name}")
    (True, False)
    """
    return bool(CHOICE_RE.search(text))


def parse(text):
    """Parse an ICU message into a list of strings."""
    parser = _Parser(text)
    nodes = parser.message(in_plural=False)
    if parser.pos != len(text):
        raise ICUSyntaxError(f"unexpected '}}' at {parser.pos}")
    return nodes


class _Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def message(self, in_plural):
        nodes, buffer = [], []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "}":
                break
            else:
                buffer.append(char)
                self.pos += 1
        if buffer:
            nodes.append("".join(buffer))
        return nodes

    def skip_space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
