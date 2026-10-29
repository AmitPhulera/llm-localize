"""ICU MessageFormat: parsing messages, and checking a translation keeps their structure.

ICU messages, used by FormatJS (react-intl), next-intl, Angular and
others, pick text by argument: ``{count, plural, one {# file} other {#
files}}``. A translation has the same arguments, but its plural cases
are the target language's CLDR categories, so the generic placeholder
check doesn't fit. Instead, each case of the translation is checked
against the matching case of the source, or its ``other`` case.
"""
import re
from collections import Counter

from llm_localize.validation import find_problem as find_text_problem
from llm_localize.validation import is_text_attribute

# An argument that chooses between cases, e.g. "{count, plural," or "{g, select,"
CHOICE_RE = re.compile(r"\{\s*[^{},\s]+\s*,\s*(?:plural|select|selectordinal)\s*,")
# Deeper than any real message, and shallow enough that parsing and checking stay within Python's recursion limit
MAX_DEPTH = 20

# Braces in literal text, rendered as look-alikes so they aren't taken for arguments
LITERAL_BRACES = str.maketrans("{}", "\ufe5b\ufe5c")
PLURAL_KEYWORDS = ("zero", "one", "two", "few", "many", "other")
# An argument's name, its kind or a case's key
TOKEN_RE = re.compile(r"[^\s{},]+")
# A choice where a tag's name would be
TAG_NAMED_BY_CHOICE_RE = re.compile(r"</?\{")
# An exact case's number, like =0, =-1 or =1.5
EXACT_CASE_RE = re.compile(r"=-?\d+(?:\.\d+)?")


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
        match = TOKEN_RE.match(self.text, self.pos)
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

    The translation must keep the same arguments. Each plural argument
    must have a case for each of ``plural_categories`` (the target
    language's), and each selectordinal one for each of
    ``ordinal_categories``, plus the source's exact cases like ``=0``; each select
    argument must keep the source's cases. Each case is then checked like
    any message, against the source case with the same key, or the
    source's ``other`` case.

    >>> source = "{n, plural, one {# file} other {# files}}"
    >>> find_problem(source, "{n, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}",
    ...              ["one", "few", "many", "other"]) is None
    True
    >>> find_problem(source, "{n, plural, one {# файл} other {# файлов}}", ["one", "few", "many", "other"])
    'plural forms'
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


def _compare(source_nodes, translation_nodes, categories, place=None):
    """``categories`` maps a choice type, like ``plural``, to the target language's categories for it, or None.

    ``place`` is where in HTML the nodes are, as ``_places`` gives it.
    """
    source_choices, translation_choices = _choices(source_nodes), _choices(translation_nodes)
    if ({name: [choice.type for choice in choices] for name, choices in source_choices.items()}
            != {name: [choice.type for choice in choices] for name, choices in translation_choices.items()}):
        return "ICU arguments"
    # The text around choices, with each choice standing in as {name}
    source_text, translation_text = _render(source_nodes), _render(translation_nodes)
    problem = find_text_problem(source_text, translation_text)
    if problem:
        return "ICU arguments" if problem == "placeholders" else problem
    # A tag named by a choice, like <{g, select, other {img}} onerror=...>, is no tag to the checks
    if len(TAG_NAMED_BY_CHOICE_RE.findall(translation_text)) > len(TAG_NAMED_BY_CHOICE_RE.findall(source_text)):
        return "HTML tags"
    # Only a plural shows the number with #; anywhere else a # the translation adds is printed as is
    if _text_hashes(translation_nodes) > _text_hashes(source_nodes):
        return "ICU arguments"
    # The same argument may choose more than once; pair each use with the translation's use in the same position
    if not source_choices:
        return None
    source_places, places = _places(source_nodes, place), _places(translation_nodes, place)
    for name, choices in source_choices.items():
        for source_choice, translation_choice in zip(choices, translation_choices[name], strict=True):
            choice_place = places[id(translation_choice)]
            # In the same attribute, so a link can't become a title's text or the other way round
            if choice_place != source_places[id(source_choice)]:
                return "HTML attributes"
            problem = _compare_choice(source_choice, translation_choice, categories, choice_place)
            if problem:
                return problem
    return None


def _places(nodes, place):
    """Return ``{id(choice): place}`` for a message level's choices, ``place`` if it's given, else where each is.

    A place is None in text, ``("text", quote, name)`` in a quoted
    attribute that holds text, like ``alt``, and ``("attribute", name)``
    elsewhere in a tag.

    >>> nodes = parse('<img alt="{n, plural, other {x}}" src="{n, plural, other {y}}"> {m, select, other {z}}')
    >>> list(_places(nodes, None).values())
    [('text', '"', 'alt'), ('attribute', 'src'), None]
    >>> list(_places(parse("Score < {n, plural, other {# points}}"), None).values())
    [None]
    """
    # Without a <, every choice is in text
    if place is None and not any("<" in node for node in nodes if isinstance(node, str)):
        return {id(node): None for node in nodes if isinstance(node, Choice)}
    places, html = {}, None if place is not None else _Html()
    for node in nodes:
        if isinstance(node, Choice):
            places[id(node)] = place if html is None else html.place()
        if html is not None:
            # Read as it goes, so each choice's place takes one pass, not a scan of all the text before it
            html.feed(_render([node]))
    return places


class _Html:
    """Where in HTML text read so far ends, tokenized as a browser does: a quote opens a value only after =."""

    def __init__(self):
        self.state, self.tag, self.name, self.quote, self.seen = "text", "", "", "", ""

    def feed(self, text):
        for char in text:
            self.step(char)

    def step(self, char):
        state, previous, self.seen = self.state, self.seen, (self.seen + char.lower())[-9:]
        if state == "text":
            if previous.endswith("<") and char.isalpha():
                self.state, self.tag = "tag", char.lower()
        elif state == "quoted":
            if char == self.quote:
                self.state = "attributes"
        elif char == ">":
            self.state = "text"
        elif state == "tag":
            if char.isspace() or char == "/":
                self.state = "attributes"
            else:
                self.tag += char.lower()
        elif state == "value":
            if char in "\"'":
                self.state, self.quote = "quoted", char
            elif not char.isspace():
                self.state = "unquoted"
        elif state == "unquoted":
            if char.isspace():
                self.state = "attributes"
        elif char == "=" and state in ("name", "after name"):
            self.state = "value"
        elif char.isspace() or char == "/":
            self.state = "after name" if state == "name" else state
        elif state == "name":
            self.name += char.lower()
        else:
            self.state, self.name = "name", char.lower()

    def place(self):
        if self.state == "text":
            return None
        if self.state == "quoted" and is_text_attribute(self.tag, self.name):
            return "text", self.quote, self.name
        return "attribute", self.name


def _compare_choice(source_choice, translation_choice, categories, place=None):
    if source_choice.offset != translation_choice.offset:
        return "ICU arguments"
    language_categories = categories.get(source_choice.type)
    problem = _case_keys_problem(source_choice, translation_choice, language_categories)
    if problem:
        return problem
    for key, translation_case in translation_choice.cases.items():
        source_case = source_choice.cases.get(key, source_choice.cases["other"])
        # A case that shows the number must keep showing it (adding it is fine: Russian "one" covers 21
        # too). Cases the translation adds that state their number (=0) or that its language never
        # uses needn't show it.
        shown = key in source_choice.cases or (not key.startswith("=") and key in (language_categories or [key]))
        if (source_choice.type != "select" and shown and _shows_number(source_case)
                and not _shows_number(translation_case)):
            return "ICU arguments"
        # A link or a handler in a case stays as it is
        if place and place[0] == "attribute" and _render(translation_case) != _render(source_case):
            return "HTML attributes"
        # A case in an attribute's text can't end the value or the tag, as `x" onerror="...` would
        if place and place[0] == "text":
            ends = place[1] + "<>"
            if Counter(c for c in _render(translation_case) if c in ends) != Counter(
                    c for c in _render(source_case) if c in ends):
                return "HTML attributes"
        problem = _compare(source_case, translation_case, categories, place)
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


def _shows_number(nodes):
    """True if a plural case has a ``#``, directly or in a select inside it, but not in a nested plural."""
    return any(
        node is NUMBER or (isinstance(node, Choice) and node.type == "select"
                           and any(_shows_number(case) for case in node.cases.values()))
        for node in nodes
    )


def _text_hashes(nodes):
    """Count the ``#`` characters in a message level's text, which are printed as ``#``."""
    return sum(node.count("#") for node in nodes if isinstance(node, str))


def _case_keys_problem(source_choice, translation_choice, language_categories):
    source_keys, translation_keys = set(source_choice.cases), set(translation_choice.cases)
    if source_choice.type == "select":
        return None if source_keys == translation_keys else "ICU select cases"
    # Exact cases like =0 must stay; the translation may add its own
    if not {key for key in source_keys if key.startswith("=")} <= translation_keys:
        return "plural forms"
    for key in translation_keys:
        if not (EXACT_CASE_RE.fullmatch(key) if key.startswith("=") else key in PLURAL_KEYWORDS):
            return "plural forms"
    if language_categories and set(language_categories) - translation_keys:
        return "plural forms"
    return None


def _render(nodes):
    """Write nodes back as text, with each argument and choice as ``{name}``, for the generic checks.

    Braces in literal text, like quoted '{name}', become look-alikes, so only
    real arguments read as placeholders: a literal can't stand in for one.

    >>> _render(parse("Hi {name}")), _render(parse("Hi '{name}'"))
    ('Hi {name}', 'Hi ﹛name﹜')
    """
    return "".join(node.translate(LITERAL_BRACES) if isinstance(node, str) else "#" if node is NUMBER
                   else node.render() for node in nodes)
