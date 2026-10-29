"""ICU MessageFormat: parsing messages, and checking a translation keeps their structure.

ICU messages, used by FormatJS (react-intl), next-intl, Angular and
others, pick text by argument: ``{count, plural, one {# file} other {#
files}}``. A translation has the same arguments, but its plural cases
are the target language's CLDR categories, so the generic placeholder
check doesn't fit. Instead, each case of the translation is checked
against the matching case of the source, or its ``other`` case.
"""
import re

from llm_localize.validation import find_problem as find_text_problem

# An argument that chooses between cases, e.g. "{count, plural," or "{g, select,"
CHOICE_RE = re.compile(r"\{\s*[^{},\s]+\s*,\s*(?:plural|select|selectordinal)\s*,")
# Deeper than any real message, and shallow enough that parsing and checking stay within Python's recursion limit
MAX_DEPTH = 20


class ICUSyntaxError(ValueError):
    pass


class _Number:
    """The ``#`` in a plural case, which shows the number. Plain ``"#"`` strings are quoted text."""

    def __repr__(self):
        return "#"


NUMBER = _Number()


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
    """Parse an ICU message into a list of strings, ``NUMBER`` markers, ``Argument`` and ``Choice`` nodes.

    >>> [type(node).__name__ for node in parse("Hi {name}, {n, plural, one {# file} other {# files}}")]
    ['str', 'Argument', 'str', 'Choice']
    >>> parse("It''s '{literal}'")
    ["It's {literal}"]
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
            elif char == "#" and in_plural:
                if buffer:
                    nodes.append("".join(buffer))
                    buffer = []
                nodes.append(NUMBER)
                self.pos += 1
            elif char == "'":
                buffer.append(self.quoted(in_plural))
            else:
                buffer.append(char)
                self.pos += 1
        if buffer:
            nodes.append("".join(buffer))
        return nodes

    def quoted(self, in_plural):
        """Read an apostrophe: '' is a literal apostrophe, and '{...}' quotes syntax characters."""
        text = self.text
        if text.startswith("''", self.pos):
            self.pos += 2
            return "'"
        special = "{}#" if in_plural else "{}"
        if self.pos + 1 < len(text) and text[self.pos + 1] in special:
            end = self.pos + 1
            chars = []
            while end < len(text):
                if text.startswith("''", end):
                    chars.append("'")
                    end += 2
                elif text[end] == "'":
                    break
                else:
                    chars.append(text[end])
                    end += 1
            self.pos = end + 1
            return "".join(chars)
        self.pos += 1
        return "'"

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
            # "#" stands for the nearest plural's number, also inside a select within it
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


def find_problem(source, translation, plural_categories=None, ordinal_categories=None):
    """Return why an ICU ``translation`` doesn't fit ``source``, or None.

    The translation must keep the same arguments and offsets. Each case
    is then checked like any message, against the source case with the
    same key, or the source's ``other`` case.

    >>> source = "{n, plural, one {# file} other {# files}}"
    >>> find_problem(source, "{n, plural, one {# fichier} many {# fichiers} other {# fichiers}}",
    ...              ["one", "many", "other"]) is None
    True
    >>> find_problem(source, "{count, plural, one {# fichier} other {# fichiers}}", ["one", "many", "other"])
    'ICU arguments'
    """
    try:
        source_nodes = parse(source)
    except ICUSyntaxError:
        return find_text_problem(source, translation)
    try:
        translation_nodes = parse(translation)
    except ICUSyntaxError:
        return "ICU syntax"
    categories = {"plural": plural_categories, "selectordinal": ordinal_categories}
    return _compare(source_nodes, translation_nodes, categories)


def _compare(source_nodes, translation_nodes, categories):
    """``categories`` maps a choice type, like ``plural``, to the target language's categories for it, or None."""
    source_choices, translation_choices = _choices(source_nodes), _choices(translation_nodes)
    if ({name: [choice.type for choice in choices] for name, choices in source_choices.items()}
            != {name: [choice.type for choice in choices] for name, choices in translation_choices.items()}):
        return "ICU arguments"
    # The text around choices, with each choice standing in as {name}
    problem = find_text_problem(_render(source_nodes), _render(translation_nodes))
    if problem:
        return "ICU arguments" if problem == "placeholders" else problem
    # The same argument may choose more than once; pair each use with the translation's use in the same position
    for name, choices in source_choices.items():
        for source_choice, translation_choice in zip(choices, translation_choices[name], strict=True):
            problem = _compare_choice(source_choice, translation_choice, categories)
            if problem:
                return problem
    return None


def _compare_choice(source_choice, translation_choice, categories):
    if source_choice.offset != translation_choice.offset:
        return "ICU arguments"
    for key, translation_case in translation_choice.cases.items():
        source_case = source_choice.cases.get(key, source_choice.cases["other"])
        problem = _compare(source_case, translation_case, categories)
        if problem:
            return problem
    return None


def _choices(nodes):
    """Group a message level's choices by argument name, in order."""
    choices = {}
    for node in nodes:
        if isinstance(node, Choice):
            choices.setdefault(node.name, []).append(node)
    return choices


def _render(nodes):
    """Write nodes back as text, with each argument and choice as ``{name}``, for the generic checks."""
    return "".join(node if isinstance(node, str) else "#" if node is NUMBER else node.render() for node in nodes)
