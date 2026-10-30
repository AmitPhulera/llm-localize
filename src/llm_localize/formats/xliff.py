"""XLIFF 1.2 files, as written by Angular's extract-i18n and most translation tools.

Each ``<trans-unit>`` holds its source and its translation, so like a
PO file one file is one target language, named by its
``target-language`` attribute or by ``--lang``. A unit is translated
when it has no ``<target>``, an empty one, or one in the
``new``/``needs-translation`` state, and the translation's state becomes
``translated``. Inline elements like ``<x/>``, ``<ph/>`` and ``<g>``
must be kept with their attributes. Units marked ``translate="no"`` are
skipped. The file is edited in place, so everything else stays as it was.
"""
import os
from functools import cached_property
from xml.parsers import expat

from llm_localize.formats.base import TranslationFile, splice, write_file
from llm_localize.formats.xml_utils import (
    BARE_AMPERSAND_RE,
    from_utf8,
    line_indent,
    set_attribute,
    tag_end,
    to_utf8,
)
from llm_localize.plurals import plural_categories
from llm_localize.units import TranslationUnit

UNTRANSLATED_STATES = {"new", "needs-translation", "initial"}


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
        return self._language or self._parsed.target_language

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
        units = []
        for key, segment in self._parsed.segments.items():
            if segment.source.strip() and (segment.target is None or not segment.target.strip()
                                           or segment.state in UNTRANSLATED_STATES):
                units.append(TranslationUnit(key=key, source=segment.source, context=segment.context))
        return units

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
                if parsed.version == "1":
                    start_tag = set_attribute(start_tag, b"state", b"translated")
                replacements.append((start, end, start_tag + text + closing))
            else:
                state = b' state="translated"' if parsed.version == "1" else b""
                # On a line of its own after the source, or right after it when the source shares its line
                newline = b"\n" + segment.indent if segment.indent else b""
                element = newline + b"<target" + state + b">" + text + b"</target>"
                replacements.append((segment.source_end, segment.source_end, element))
        write_file(self.path, from_utf8(splice(data, replacements), parsed.encoding, parsed.bom))


class _Segment:
    def __init__(self, context):
        self.context = context
        self.source = ""
        self.source_end = 0
        self.indent = b""
        self.target = None
        self.target_span = None
        self.target_inner = None
        self.state = None
        self.segment_tag = None


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
    unit = {}

    def local(tag):
        return tag.rpartition(":")[2]

    def start(tag, attrs):
        name = local(tag)
        start_index = parser.CurrentByteIndex
        inner_start = tag_end(data, start_index)
        names = [entry[0] for entry in stack]
        if name == "xliff":
            parsed.version = "2" if attrs.get("version", "").startswith("2") else "1"
        elif name == "file" and attrs.get("target-language"):
            parsed.target_language = parsed.target_language or attrs["target-language"]
        elif name in ("trans-unit", "unit"):
            unit.clear()
            unit.update(id=attrs.get("id", ""), skip=attrs.get("translate") == "no", notes=[], segments=0,
                        state=None, segment_tag=None, read=[])
        elif name in ("source", "target") and _in_segment(names):
            if name == "source":
                unit["segments"] += 1
                key = f"{unit['id']}#{unit['segments']}" if parsed.version == "2" else unit["id"]
                if key in parsed.segments:
                    key = f"{key}#{len(parsed.segments)}"
                segment = _Segment(context="")
                segment.indent = line_indent(data, start_index)
                segment.segment_tag = unit["segment_tag"]
                segment.state = unit["state"]
                unit["current"] = None if unit["skip"] else (key, segment)
        stack.append((name, attrs, start_index, inner_start))

    def end(tag):
        name, attrs, start_index, inner_start = stack.pop()
        end_index = parser.CurrentByteIndex
        self_closing = data[inner_start - 2:inner_start] == b"/>"
        inner_end = inner_start if self_closing else end_index
        element_end = inner_start if self_closing else data.index(b">", end_index) + 1
        names = [entry[0] for entry in stack]
        if name == "note" and ("trans-unit" in names or "unit" in names):
            unit["notes"].append(" ".join(data[inner_start:inner_end].decode().split()))
        elif name in ("source", "target") and _in_segment(names) and unit.get("current"):
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
                if parsed.version == "1":
                    segment.state = attrs.get("state")
        elif name in ("trans-unit", "unit"):
            context = "; ".join(filter(None, [*unit["notes"], f"ID: {unit['id']}"]))
            # Notes may come after the sources, so context is set once the unit is read
            for segment in unit["read"]:
                segment.context = context

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{path} is not valid XML: {e}") from e
    return parsed


def _in_segment(names):
    """True if a source or target is a unit's own, not one inside alt-trans or a note."""
    return bool(names) and names[-1] in ("trans-unit", "segment")
