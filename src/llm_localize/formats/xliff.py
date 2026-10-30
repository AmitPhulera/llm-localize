"""XLIFF 1.2 and 2.0 files, as written by Angular's extract-i18n and most translation tools.

Each ``<trans-unit>`` (1.2) or ``<segment>`` (2.0) holds its source and
its translation, so like a PO file one file is one target language,
named by its ``target-language`` (1.2) or ``trgLang`` (2.0) attribute
or by ``--lang``. A unit is translated when it has no ``<target>``, an
empty one, or one in the ``new``/``needs-translation`` (1.2) or
``initial`` (2.0) state, and the translation's state becomes
``translated``. Inline elements like ``<x/>``, ``<ph/>`` and ``<g>``
must be kept with their attributes. Units marked ``translate="no"`` are
skipped. The file is edited in place, so everything else stays as it was.
"""
import os
import re
from collections import Counter
from functools import cached_property
from xml.parsers import expat
from xml.sax.saxutils import quoteattr, unescape

from llm_localize import icu
from llm_localize.formats.base import TranslationFile, splice, write_file
from llm_localize.formats.monolingual import _is_language_code
from llm_localize.formats.xml_utils import (
    BARE_AMPERSAND_RE,
    changes_tags,
    decode_character_references,
    from_utf8,
    line_indent,
    open_tag,
    set_attribute,
    tag_end,
    to_utf8,
)
from llm_localize.plurals import compatible_languages, ordinal_categories, plural_categories
from llm_localize.units import TranslationUnit

UNTRANSLATED_STATES = {"new", "needs-translation", "initial"}
# The halves of a pair written as two placeholders, as the start and end tags they stand for
PAIR_HALVES = {"sc": "<sc>", "ec": "</sc>", "bx": "<bx>", "ex": "</bx>", "sm": "<sm>", "em": "</sm>"}
ELEMENT_ID_RE = re.compile(r"""\sid\s*=\s*["']([^"']*)["']""")
CDATA_OR_ELEMENT_RE = re.compile(r"<!\[CDATA\[.*?\]\]>|<[^<>]+>", re.DOTALL)


def _language_in_name(path):
    """Return the language code in a file's name, like fr in messages.fr.xlf, or None.

    >>> _language_in_name("src/locale/messages.pt-BR.xlf"), _language_in_name("messages.xlf")
    ('pt-BR', None)
    """
    *parts, _ = os.path.basename(path).split(".")
    return next((part for part in reversed(parts) if _is_language_code(part)), None)


class XliffFile(TranslationFile):
    name = "xliff"
    extensions = (".xlf", ".xliff")

    def __init__(self, path, language=None):
        super().__init__(path)
        self._language = language

    @classmethod
    def open(cls, path, language=None, source_language=None, source_path=None):
        return cls(path, language=language)

    @property
    def language(self):
        # Angular's extract-i18n writes no target language: its copy for French is named messages.fr.xlf
        return self._language or self._parsed.target_language or _language_in_name(self.path)

    @property
    def instructions(self):
        categories = ", ".join(plural_categories(self.language or "en"))
        return (
            "Messages are XLIFF segments: keep inline XML elements like <x id=\"...\"/>, <ph id=\"...\"/>, "
            "<g>...</g> and <pc>...</pc> exactly as they are, with their attributes, translating only "
            "the text around and inside them. Keep XML entities like &amp; and &lt; as they are. A message "
            "in ICU MessageFormat, like \"{VAR_PLURAL, plural, =1 {one item} other {# items}}\", must keep "
            "its argument names, exact cases like =1 and select cases, and give each plural argument one "
            f"case per plural category of the target language: {categories}. In ICU messages an apostrophe "
            "before {, } or # starts quoted text, so write it twice: l''{app}, not l'{app}."
        )

    @cached_property
    def _parsed(self):
        return _read(self.path)

    def untranslated_units(self):
        if not self.language:
            raise ValueError(f"Can't tell the target language of {self.path}; pass it with --lang")
        declared = self._parsed.target_language
        # Another variant of the declared language may be given, like zh-Hans for zh_CN, but not one with other
        # plural rules or another script, like pt-PT for pt_BR or zh-Hant for zh_Hans
        if self._language and declared and not compatible_languages(declared, self._language):
            raise ValueError(f"{self.path} declares its target language as {declared}, not {self._language}; "
                             "fix it, or don't pass a language")
        units = []
        for key, segment in self._parsed.segments.items():
            if segment.source.strip() and (segment.target is None or not segment.target.strip()
                                           or segment.state in UNTRANSLATED_STATES):
                units.append(TranslationUnit(key=key, source=segment.source, context=segment.context))
        return units

    def find_problem(self, source, translation):
        # Inline elements' attributes, like equiv-text="{{ name }}", aren't ICU, so the ICU check sees tokens.
        # The rest is checked as an app reads it: &#37;s is %s, and &lt;a href="..."&gt; is a link.
        masked_source, masked_translation = _as_read(_mask_elements(source)), _as_read(_mask_elements(translation))
        choice = icu.is_icu_choice(masked_source)
        if choice:
            problem = icu.find_problem(masked_source, masked_translation, list(plural_categories(self.language)),
                                       ordinal_categories(self.language))
        else:
            problem = super().find_problem(masked_source, masked_translation)
        if problem:
            return problem
        if changes_tags(source, translation, counted=not choice):
            return "XML tags"
        try:
            expat.ParserCreate().Parse(f"<r>{BARE_AMPERSAND_RE.sub('&amp;', translation)}</r>", True)
        except expat.ExpatError:
            return "XML"
        return None

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = BARE_AMPERSAND_RE.sub("&amp;", translation)

    def save(self):
        """Write the file: its original bytes, with each translated segment's target and state replaced."""
        parsed = self._parsed
        data = parsed.data
        replacements = []
        for key, translation in self._applied.items():
            segment = parsed.segments[key]
            text = translation.encode()
            if segment.target_span:
                start, end = segment.target_span
                start_tag, closing = data[start:segment.target_inner[0]], data[segment.target_inner[1]:end]
                if start_tag.endswith(b"/>"):
                    # Closed with its own name, which may have a prefix like x:target
                    name = re.match(rb"<([^\s/>]+)", start_tag).group(1)
                    start_tag, closing = open_tag(start_tag), b"</" + name + b">"
                if parsed.version == "1":
                    start_tag = set_attribute(start_tag, b"state", b"translated")
                missing = segment.namespaces.keys() - segment.target_attrs
                start_tag = _with_namespaces(start_tag, {name: segment.namespaces[name] for name in missing})
                replacements.append((start, end, start_tag + text + closing))
            else:
                state = b' state="translated"' if parsed.version == "1" else b""
                # On a line of its own after the source, or right after it when the source shares its line
                newline = b"\n" + segment.indent if segment.indent else b""
                name = segment.target_name
                start_tag = _with_namespaces(b"<" + name + state + b">", segment.namespaces)
                element = newline + start_tag + text + b"</" + name + b">"
                replacements.append((segment.source_end, segment.source_end, element))
            if parsed.version == "2" and segment.segment_tag:
                start, end = segment.segment_tag
                replacements.append((start, end, set_attribute(data[start:end], b"state", b"translated")))
        write_file(self.path, from_utf8(splice(data, replacements), parsed.encoding, parsed.bom))


def _as_read(text):
    """Return a segment's text as XML reads it, with its character references and entities like &lt; replaced.

    >>> _as_read("50&#37; &lt;b&gt;bold&lt;/b&gt; &amp;lt; &quot;")
    '50% <b>bold</b> &lt; "'
    """
    return unescape(decode_character_references(text), {"&quot;": '"', "&apos;": "'"})


def _mask_elements(text):
    """Return the text with paired inline elements as bare tags, and placeholders as ``%(inline_name_id)s``.

    Placeholders may then move, as word order needs, while pairs like
    ``<g>`` still nest; ``changes_tags`` checks each is kept as it is.

    HTML in a CDATA section is text to XLIFF, so it's left as it is, for the
    HTML check to compare.

    >>> _mask_elements('Hi <x id="N" equiv-text="{{ name }}"/> <g id="1">Bob</g> <![CDATA[<a href="/x">]]>')
    'Hi  %(inline_x_N)s <g>Bob</g> <![CDATA[<a href="/x">]]>'
    """
    def name_alone(match):
        tag = match.group()
        if tag.startswith("<![CDATA["):
            return tag
        name = re.match(r"</?([^\s/>]+)", tag).group(1)
        if tag.endswith("/>"):
            # Half of a pair, which must stay in order: 2.0's <sc/> and <ec/> and <sm/> and <em/>, 1.2's
            # <bx/> and <ex/>, and Angular's <x id="START_BOLD_TEXT"/> and <x id="CLOSE_BOLD_TEXT"/>
            local, element_id = name.rpartition(":")[2].lower(), ELEMENT_ID_RE.search(tag)
            pair = re.fullmatch(r"(START|CLOSE)_(\w+)", element_id.group(1)) if element_id else None
            if local in PAIR_HALVES:
                return PAIR_HALVES[local]
            if pair:
                return f"<{'/' if pair.group(1) == 'CLOSE' else ''}x-{pair.group(2).lower()}>"
            # A placeholder, like <x/> or <ph/>: a named placeholder, which may move past markup too, written
            # without braces, so an apostrophe before it, as in l'<x/>, isn't ICU quoting, and after a space, so
            # a % before it, as in Turkish's %<x/>, isn't taken for part of it. Its id is part of its name, so
            # placeholders can't swap places between an ICU message's cases; other characters are written as
            # codes, so ids like a-b and a_b stay apart
            name = name.lower() + ("_" + element_id.group(1) if element_id else "")
            return " %(inline_" + re.sub(r"\W", lambda char: f"-{ord(char.group()):x}-", name) + ")s"
        return f"</{name}>" if tag.startswith("</") else f"<{name}>"
    return CDATA_OR_ELEMENT_RE.sub(name_alone, text)


def _with_namespaces(start_tag, namespaces):
    """Return an opened target start tag declaring ``namespaces``, the source's, which its text may use."""
    declarations = b"".join(f" {name}={quoteattr(namespaces[name])}".encode() for name in sorted(namespaces))
    return start_tag[:-1] + declarations + start_tag[-1:]


class _Segment:
    def __init__(self, context):
        self.context = context
        self.source = ""
        self.source_end = 0
        self.indent = b""
        self.target = None
        self.target_span = None
        self.target_inner = None
        self.target_attrs = set()
        # The namespaces the source declares, like xmlns:x, as {attribute: URI}
        self.namespaces = {}
        self.state = None
        self.segment_tag = None
        # A new target is named like the source, x:target for x:source, so it's in the same namespace
        self.target_name = b"target"


class _Parsed:
    def __init__(self, data):
        self.data = data
        self.encoding = None
        self.bom = b""
        self.version = "1"
        self.target_language = None
        self.segments = {}


def _read(path):
    if not os.path.exists(path):
        raise ValueError(f"{path} doesn't exist")
    with open(path, "rb") as f:
        data, encoding, bom = to_utf8(f.read(), path)
    parsed = _Parsed(data)
    parsed.encoding, parsed.bom = encoding, bom
    parser = expat.ParserCreate("UTF-8")
    stack = []  # (local name, attrs, start index, inner start)
    open_elements = Counter()  # how many of each element are open, so ancestors needn't be listed per tag
    untranslatable = []  # for each open element, whether it's marked translate="no", itself or by a parent
    unit = {}

    def local(tag):
        return tag.rpartition(":")[2]

    def start(tag, attrs):
        name = local(tag)
        start_index = parser.CurrentByteIndex
        inner_start = tag_end(data, start_index)
        parent = stack[-1][0] if stack else ""
        # translate="no" holds for the element's children too, unless one says translate="yes"
        inherited = bool(untranslatable) and untranslatable[-1]
        untranslatable.append(attrs.get("translate", "no" if inherited else "yes") == "no")
        if name == "xliff":
            parsed.version = "2" if attrs.get("version", "").startswith("2") else "1"
            parsed.target_language = attrs.get("trgLang") or parsed.target_language
        elif name == "file" and attrs.get("target-language"):
            language = attrs["target-language"]
            if parsed.target_language and parsed.target_language.lower() != language.lower():
                raise ValueError(f"{path} has files for more than one target language, "
                                 f"{parsed.target_language} and {language}; translate them as separate files")
            parsed.target_language = language
        elif name in ("trans-unit", "unit"):
            unit.clear()
            unit.update(id=attrs.get("id", ""), skip=untranslatable[-1], notes=[], segments=0,
                        state=None, segment_tag=None, read=[])
        elif name == "segment" and open_elements["unit"]:
            unit["segment_tag"] = (start_index, inner_start)
            unit["state"] = attrs.get("state")
        elif name in ("source", "target") and _in_segment(parent) and (open_elements["trans-unit"]
                                                                         or open_elements["unit"]):
            if name == "source":
                unit["segments"] += 1
                key = f"{unit['id']}#{unit['segments']}" if parsed.version == "2" else unit["id"]
                # A repeated id gets a number, one no other unit's id has taken
                number, base = len(parsed.segments), key
                while key in parsed.segments:
                    key, number = f"{base}#{number}", number + 1
                segment = _Segment(context="")
                segment.indent = line_indent(data, start_index)
                segment.segment_tag = unit["segment_tag"]
                segment.state = unit["state"]
                segment.target_name = tag.rpartition(":")[0].encode() + b":target" if ":" in tag else b"target"
                segment.namespaces = {name: value for name, value in attrs.items()
                                      if name == "xmlns" or name.startswith("xmlns:")}
                unit["current"] = None if unit["skip"] else (key, segment)
        stack.append((name, attrs, start_index, inner_start))
        open_elements[name] += 1

    def end(tag):
        name, attrs, start_index, inner_start = stack.pop()
        untranslatable.pop()
        end_index = parser.CurrentByteIndex
        self_closing = data[inner_start - 2:inner_start] == b"/>"
        inner_end = inner_start if self_closing else end_index
        element_end = inner_start if self_closing else data.index(b">", end_index) + 1
        open_elements[name] -= 1
        parent = stack[-1][0] if stack else ""
        if name == "note" and (open_elements["trans-unit"] or open_elements["unit"]):
            unit["notes"].append(" ".join(data[inner_start:inner_end].decode().split()))
        elif (name in ("source", "target") and _in_segment(parent) and unit.get("current")
              and (open_elements["trans-unit"] or open_elements["unit"])):
            key, segment = unit["current"]
            raw = data[inner_start:inner_end].decode()
            if name == "source":
                segment.source = raw
                segment.source_end = element_end
                parsed.segments[key] = segment
                unit["read"].append(segment)
            else:
                segment.target = raw
                segment.target_span = (start_index, element_end)
                segment.target_inner = (inner_start, inner_end)
                segment.target_attrs = set(attrs)
                if parsed.version == "1":
                    segment.state = attrs.get("state")
        elif name == "seg-source" and parent == "trans-unit" and unit.get("current"):
            # A new target goes after it: XLIFF 1.2 has source, seg-source, target in that order
            unit["current"][1].source_end = element_end
        elif name in ("trans-unit", "unit"):
            context = "; ".join(filter(None, [*unit["notes"], f"ID: {unit['id']}"]))
            # Notes may come after the sources, so context is set once the unit is read
            for segment in unit["read"]:
                segment.context = context

    def doctype(*args):
        # XLIFF never has one, and its entities could expand a small upload enormously
        raise ValueError(f"{path} has a DOCTYPE, which XLIFF files don't use")

    parser.StartDoctypeDeclHandler = doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{path} is not valid XML: {e}") from e
    return parsed


def _in_segment(parent):
    """True if a source or target, in ``parent``, is a unit's own, not one inside alt-trans or a note."""
    return parent in ("trans-unit", "segment")
