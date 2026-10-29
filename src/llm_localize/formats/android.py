"""Android string resources: ``res/values/strings.xml`` and its translations, like ``res/values-fr/strings.xml``.
"""
import os
import re
from functools import cached_property
from pathlib import Path
from xml.parsers import expat

from llm_localize.formats.base import splice, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile, _is_language_code
from llm_localize.formats.xml_utils import BARE_AMPERSAND_RE, line_indent, open_tag, tag_end

# A CDATA section, whose & needn't be escaped, or a tag
CDATA_OR_TAG_RE = re.compile(r"(<!\[CDATA\[.*?\]\]>|<[^>]*>)", re.S)
# Not escaped: after no backslash, or after escaped ones, whose run is kept as group 1, as in "C:\\"
UNESCAPED = r"(?<!\\)((?:\\\\)*)"
UNESCAPED_QUOTE_RE = re.compile(UNESCAPED + '"')
UNESCAPED_APOSTROPHE_RE = re.compile(UNESCAPED + "'")
# An escaped quote or apostrophe
ESCAPED_QUOTE_RE = re.compile(UNESCAPED + r"\\(['\"])")
NEW_FILE = '<?xml version="1.0" encoding="utf-8"?>\n'


class AndroidFile(MonolingualFile):
    name = "android"
    extensions = (".xml",)

    def language_from_path(self):
        match = _values_dir(self.path)
        return match[1] if match else None

    def source_path_candidates(self):
        match = _values_dir(self.path)
        if match:
            part_index, _, other_qualifiers = match
            parts = list(Path(self.path).parts)
            parts[part_index] = "-".join(["values", *other_qualifiers])
            yield Path(*parts)

    def read_messages(self, path):
        messages = {}
        for key, element in _read(path).elements.items():
            context = f"Key: {element.name}"
            messages[key] = Message(text=_decode(element.raw)[0], context=context)
        return messages

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = translation

    def save(self):
        """Write the target file: its original bytes, with each translation replacing or added after the rest."""
        source = _read(self.source_path)
        target = _read(self.path)
        if not target.data:
            # A source with no strings may be <resources/>, which the new file opens
            root = source.root_start_tag
            root = open_tag(root)
            target = _Resources((NEW_FILE + root + "\n</resources>\n").encode())
            target.root_start = len(NEW_FILE)
            target.root_tag_end = target.root_start + len(root.encode())
            target.root_end = target.data.rindex(b"</resources>")
        data = target.data
        indent = source.indent
        replacements, additions = [], []
        for key, translation in self._applied.items():
            text = _element_text(source.elements[key], translation, self.plural_categories, indent).encode()
            if key in target.elements:
                replacements.append((target.elements[key].start, target.elements[key].end, text))
            else:
                additions.append(indent.encode() + text + b"\n")
        replacements.append((target.root_end, target.root_end, b"".join(additions)))
        write_file(self.path, splice(data, replacements))


def _values_dir(path):
    """Return ``(part index, language, other qualifiers)`` for the ``values-`` directory naming a language.

    >>> _values_dir("res/values-pt-rBR/strings.xml"), _values_dir("res/values-b+sr+Latn-land/strings.xml")
    ((1, 'pt-BR', []), (1, 'sr-Latn', ['land']))
    >>> _values_dir("res/values-night/strings.xml") is None
    True
    """
    parts = Path(path).parts
    for part_index in reversed(range(len(parts))):
        qualifiers = parts[part_index].split("-")
        if qualifiers[0] != "values":
            continue
        for index, qualifier in enumerate(qualifiers[1:], start=1):
            if qualifier.startswith("b+"):
                return part_index, "-".join(qualifier[2:].split("+")), qualifiers[1:index] + qualifiers[index + 1:]
            if qualifier.islower() and _is_language_code(qualifier):
                language, end = qualifier, index + 1
                if end < len(qualifiers) and re.fullmatch(r"r[A-Z]{2}", qualifiers[end]):
                    language, end = f"{qualifier}-{qualifiers[end][1:]}", end + 1
                return part_index, language, qualifiers[1:index] + qualifiers[end:]
    return None


def _decode(raw):
    r"""Return the text to translate for a resource's raw XML content, and whether it was in double quotes.

    The XML (entities, tags) is kept; only the escaping of quotes is undone,
    so the model sees plain apostrophes. Unescaped double quotes outside
    tags are Android's way of keeping spaces and apostrophes, wherever they
    are, so they're taken out, and the translation is written in quotes.

    >>> _decode(r'Don\'t say \"hi\"')
    ('Don\'t say "hi"', False)
    >>> _decode('"  Spaced\'s "'), _decode('"Hello" and "bye"'), _decode('<b id="x">"Hi"</b>')
    (("  Spaced's ", True), ('Hello and bye', True), ('<b id="x">Hi</b>', True))
    """
    parts = CDATA_OR_TAG_RE.split(raw.strip())
    quoted = any(UNESCAPED_QUOTE_RE.search(part) for part in parts[::2])
    if quoted:
        parts[::2] = [UNESCAPED_QUOTE_RE.sub(r"\1", part) for part in parts[::2]]
    text = "".join(parts) if quoted else raw
    return ESCAPED_QUOTE_RE.sub(r"\1\2", text), quoted


def _encode(text, quoted):
    r"""Escape translated text for a resource, outside its tags.

    >>> print(_encode('L\'app "Notes" & <b>co</b>', quoted=False))
    L\'app \"Notes\" &amp; <b>co</b>
    >>> print(_encode("@home", quoted=False), _encode("L'été", quoted=True))
    \@home "L'été"
    >>> print(_encode("<![CDATA[<b>Bold</b> & co's]]>", quoted=False))
    <![CDATA[<b>Bold</b> & co\'s]]>
    """
    parts = CDATA_OR_TAG_RE.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = _escape_quotes(BARE_AMPERSAND_RE.sub("&amp;", parts[index]), quoted)
    for index in range(1, len(parts), 2):
        # CDATA is text to Android, so its quotes are escaped too, but & is literal there
        if parts[index].startswith("<![CDATA["):
            parts[index] = "<![CDATA[" + _escape_quotes(parts[index][len("<![CDATA["):-len("]]>")], quoted) + "]]>"
    encoded = "".join(parts)
    if quoted:
        return f'"{encoded}"'
    return "\\" + encoded if encoded[:1] in ("@", "?") else encoded


def _escape_quotes(text, quoted):
    text = UNESCAPED_QUOTE_RE.sub(r'\1\\"', text)
    return text if quoted else UNESCAPED_APOSTROPHE_RE.sub(r"\1\\'", text)


def _element_text(element, translation, categories, indent):
    return f"{element.start_tag}{_encode(translation, _decode(element.raw)[1])}</string>"


class _Element:
    def __init__(self, tag, name, start, start_tag, comment, translatable=True):
        self.tag, self.name, self.start, self.start_tag, self.comment = tag, name, start, start_tag, comment
        self.translatable = translatable
        self.raw = ""
        self.items = {}
        self.end = start


class _Resources:
    """A parsed resources file: its bytes, root tag, translatable elements by key, and where to add more."""

    def __init__(self, data=b""):
        self.data = data
        self.root_start_tag = '<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2">'
        self.root_start = self.root_tag_end = self.root_end = 0
        self.elements = {}
        self.indent = "    "


def _read(path):
    if not os.path.exists(path):
        return _Resources()
    with open(path, "rb") as f:
        data = f.read()
    resources = _Resources(data)
    parser = expat.ParserCreate("utf-8")
    stack = []

    def start(tag, attrs):
        start_index = parser.CurrentByteIndex
        # Only the root and the resources are kept. Finding where every nested element's tag ends would
        # be slow for those from an entity, each placed at its reference.
        if len(stack) > 1:
            stack.append((tag, attrs, None))
            return
        if not data.startswith(b"<", start_index):
            raise ValueError(f"{path} has a resource from an entity, which can't be translated where it is")
        inner_start = tag_end(data, start_index)
        if not stack:
            resources.root_start_tag = data[start_index:inner_start].decode()
            resources.root_start, resources.root_tag_end = start_index, inner_start
        elif len(stack) == 1 and tag == "string":
            element = _Element(tag, attrs.get("name", ""), start_index, data[start_index:inner_start].decode(), "")
            if not resources.elements and line_indent(data, start_index):
                resources.indent = line_indent(data, start_index).decode()
            resources.elements[f"{tag}/{element.name}"] = element
        stack.append((tag, attrs, inner_start))

    def end(tag):
        _, attrs, inner_start = stack.pop()
        if inner_start is None:
            return
        end_index = parser.CurrentByteIndex
        self_closing = data[inner_start - 2:inner_start] == b"/>"
        if not stack:
            resources.root_end = inner_start if self_closing else end_index
            return
        raw = "" if self_closing else data[inner_start:end_index].decode()
        element_end = inner_start if self_closing else data.index(b">", end_index) + 1
        if len(stack) == 1:
            element = resources.elements.get(f"{tag}/{attrs.get('name', '')}")
            if element:
                element.raw, element.end = raw, element_end

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(data, True)
    # Only elements that were read in full count; resources without a name can't be matched
    resources.elements = {key: element for key, element in resources.elements.items() if element.name}
    return resources
