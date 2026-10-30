"""Android string resources: ``res/values/strings.xml`` and its translations, like ``res/values-fr/strings.xml``.

``<string>`` and ``<plurals>`` elements are translated; strings marked
``translatable="false"`` and references like ``@string/name`` are not,
and ``<string-array>`` elements are left alone. The language comes from
the ``values-`` directory's qualifiers (``values-pt-rBR``,
``values-b+sr+Latn``), and the source is the ``values`` directory
without them. Translations are added to the end of an existing file, or
replace empty elements in place, so the rest of the file is kept byte
for byte.
"""
import bisect
import os
import re
from collections import Counter
from functools import cached_property
from pathlib import Path
from xml.parsers import expat

from llm_localize.formats.base import splice, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile, _is_language_code
from llm_localize.formats.xml_utils import (
    BARE_AMPERSAND_RE,
    changes_tags,
    decode_character_references,
    line_indent,
    open_tag,
    tag_end,
    to_utf8,
)

NAMESPACE_RE = re.compile(r"""\sxmlns:([\w.-]+)\s*=\s*("[^"]*"|'[^']*')""")
# A CDATA section, whose & needn't be escaped, or a tag
CDATA_OR_TAG_RE = re.compile(r"(<!\[CDATA\[.*?\]\]>|<[^>]*>)", re.S)
# An internal entity's declaration, like <!ENTITY appname "Notes">
ENTITY_RE = re.compile(rb"""<!ENTITY\s+([\w.-]+)\s+("[^"]*"|'[^']*')\s*>""")
# Whitespace and a comment or processing instruction, as may come before a DOCTYPE
PROLOG_ITEM_RE = re.compile(rb"\s*(?:<\?.*?\?>|<!--.*?-->)", re.S)
# Not escaped: after no backslash, or after escaped ones, whose run is kept as group 1, as in "C:\\"
UNESCAPED = r"(?<!\\)((?:\\\\)*)"
UNESCAPED_QUOTE_RE = re.compile(UNESCAPED + '"')
UNESCAPED_APOSTROPHE_RE = re.compile(UNESCAPED + "'")
# An escaped quote or apostrophe
ESCAPED_QUOTE_RE = re.compile(UNESCAPED + r"\\(['\"])")
# A reference to an entity a DOCTYPE declares, not one of XML's own like &amp;
ENTITY_REFERENCE_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos);)([A-Za-z_][\w.-]*);")
# An xliff:g placeholder's start or end tag; only real ones, not escaped ones, which are markup
XLIFF_G_RE = re.compile(r"</?xliff:g\b[^<>]*>")
# XML's own entities, like &lt;
PREDEFINED_ENTITY_RE = re.compile(r"&(amp|gt|quot|apos);")
# Elements Html.fromHtml reads, and ones that change what follows with no attribute; any other with an
# attribute is markup too
KNOWN_ELEMENTS = frozenset(
    "a b big blockquote br cite del dfn div em font h1 h2 h3 h4 h5 h6 i img li p s small span strike strong "
    "sub sup tt u ul script style svg math".split())
# An escaped tag's start, its name ending where a browser ends it
ESCAPED_TAG_START_RE = re.compile(r"&lt;(/?[A-Za-z][^\s/>&=\\]*)")
# &lt; is left out: _unescape_tags decides which are markup
PREDEFINED_ENTITIES = {"amp": "&", "gt": ">", "quot": '"', "apos": "'"}
# Android's \\n or \\t, after any escaped backslashes
_WHITESPACE_ESCAPE_RE = re.compile(UNESCAPED + r"\\([nt])")
# Android's \\u0025, after any escaped backslashes
_UNICODE_ESCAPE_RE = re.compile(UNESCAPED + r"\\u([0-9A-Fa-f]{4})")
# A backslash, newline or tab escape, like \\ or \n; escaped quotes may differ, as apostrophes do
ESCAPE_RE = re.compile(r"\\[\\nt]")
# A reference to another resource, like @string/app_name or ?attr/color, which isn't text
REFERENCE_RE = re.compile(r"\s*[@?](?:[\w.]+:)?[\w.]+/[\w.]+\s*")

NEW_FILE = '<?xml version="1.0" encoding="utf-8"?>\n'


class AndroidFile(MonolingualFile):
    name = "android"
    extensions = (".xml",)
    instructions = (
        "Messages are Android string resources, and each one's context gives its resource name. "
        "Keep format specifiers like %1$s, %2$d and %s, escapes like \\n and \\u2026, inline tags "
        "like <b>, and <xliff:g> elements with their content, exactly as they are. Write apostrophes "
        "and quotes plainly, without backslashes: they are escaped when saved."
    )

    def language_from_path(self):
        match = _values_dir(self.path)
        return match[1] if match else None

    def source_path_candidates(self):
        match = _values_dir(self.path, self._language)
        if match:
            part_index, _, other_qualifiers = match
            parts = list(Path(self.path).parts)
            parts[part_index] = "-".join(["values", *other_qualifiers])
            yield Path(*parts)

    def read_messages(self, path, references=False):
        """Return the file's strings and plurals; references like ``@string/name`` only with ``references``.

        A reference isn't text to translate, but in a target it stands for
        the string, as an alias another language chose, so it counts there.
        """
        messages = {}
        for key, element in _read(path).elements.items():
            context = f"Key: {element.name}" + (f". Comment: {element.comment}" if element.comment else "")
            if element.tag == "plurals":
                plurals = {quantity: _decode(raw)[0] for quantity, raw in element.items.items()}
                messages[key] = Message(plurals=plurals, context=context, translatable=element.translatable)
            elif references or not REFERENCE_RE.fullmatch(element.raw):
                messages[key] = Message(text=_decode(element.raw)[0], context=context,
                                        translatable=element.translatable)
        return messages

    @cached_property
    def target_messages(self):
        return self.read_messages(self.path, references=True)

    def find_problem(self, source, translation):
        # &#37;s and \\u0025s are %s to Android, so they're checked as that
        # <xliff:g id="..."> placeholders may move, as word order needs, past each other and markup alike: their
        # content, like %1$s, is checked as text, and changes_tags checks each tag is kept as it is
        problem = super().find_problem(_as_android_reads(XLIFF_G_RE.sub("", source)),
                                       _as_android_reads(XLIFF_G_RE.sub("", translation)))
        if problem:
            return problem
        if changes_tags(source, translation):
            return "XML tags"
        # An entity the DOCTYPE declares may stand for markup or a placeholder, so each stays as it is
        if Counter(ENTITY_REFERENCE_RE.findall(source)) != Counter(ENTITY_REFERENCE_RE.findall(translation)):
            return "entities"
        # The model sees Android's escapes as written; dropping a backslash would change the text
        if Counter(ESCAPE_RE.findall(source)) != Counter(ESCAPE_RE.findall(translation)):
            return "escapes"
        # Parsed under the source's DOCTYPE, so entities it declares, like &appname;, are known
        text = _encode(translation, quoted=False)
        try:
            expat.ParserCreate().Parse(f"{self._source_doctype}<resources>{text}</resources>", True)
        except expat.ExpatError:
            return "XML"
        return None

    @cached_property
    def _source_doctype(self):
        return _read(self.source_path).doctype.decode()

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = self.with_translated_forms(key, translation)

    def save(self):
        """Write the target file: its original bytes, with each translation replacing or added after the rest."""
        source = _read(self.source_path)
        target = _read(self.path)
        if not target.data:
            # With the source's DOCTYPE, for the entities its strings use
            head = NEW_FILE + (source.doctype.decode() + "\n" if source.doctype else "")
            # A source with no strings may be <resources/>, which the new file opens
            root = source.root_start_tag
            root = open_tag(root)
            target = _Resources((head + root + "\n</resources>\n").encode())
            target.root_start = len(head.encode())
            target.root_tag_end = target.root_start + len(root.encode())
            target.root_end = target.data.rindex(b"</resources>")
        data = target.data
        # Match the target's indentation, or the source's for a new file
        indent = target.indent if target.elements else source.indent
        replacements, additions = [], []
        for key, translation in self._applied.items():
            # An element the target has keeps its own start tag, and attributes like formatted="false"
            own = target.elements[key].start_tag if key in target.elements else None
            if own:
                own = open_tag(own)
            text = _element_text(source.elements[key], translation, self.plural_categories, indent, own).encode()
            if key in target.elements:
                replacements.append((target.elements[key].start, target.elements[key].end, text))
            else:
                additions.append(indent.encode() + text + b"\n")
        # The source's namespaces, like xmlns:xliff, that the new elements use
        written = b"".join(text for _, _, text in replacements) + b"".join(additions)
        root_tag = _with_namespaces(data[target.root_start:target.root_tag_end].decode(), source.root_start_tag,
                                    written.decode())
        if root_tag.endswith("/>"):
            # <resources/>: open it up to hold what's added
            closing = "\n" + b"".join(additions).decode() + "</resources>" if additions else ""
            root_tag = open_tag(root_tag) + closing if additions else root_tag
        else:
            replacements.append((target.root_end, target.root_end, b"".join(additions)))
        replacements.append((target.root_start, target.root_tag_end, root_tag.encode()))
        if source.doctype and not target.doctype:
            # The source's entities, like &appname;, that translations may use
            replacements.append((target.root_start, target.root_start, source.doctype + b"\n"))
        elif source.doctype:
            # A DOCTYPE of its own: the source's entities it lacks are added to it
            missing = sorted(_entities(source.doctype).keys() - _entities(target.doctype).keys())
            if missing:
                start = data.find(target.doctype)
                declarations = b"".join(_entities(source.doctype)[name] for name in missing)
                replacements.append((start, start + len(target.doctype),
                                     _with_entities(target.doctype, declarations)))
        write_file(self.path, splice(data, replacements))


def _with_namespaces(root_tag, source_root_tag, text):
    """Return ``root_tag`` with the source's namespace declarations that ``text`` uses and it lacks.

    >>> _with_namespaces("<resources>", '<resources xmlns:xliff="urn:x" xmlns:t="urn:t">', '<xliff:g id="n"/>')
    '<resources xmlns:xliff="urn:x">'
    >>> _with_namespaces('<resources xmlns:xliff="urn:x"/>', '<resources xmlns:xliff="urn:x">', "<xliff:g/>")
    '<resources xmlns:xliff="urn:x"/>'
    """
    declared = {name for name, _ in NAMESPACE_RE.findall(root_tag)}
    missing = [f" {match.group().strip()}" for match in NAMESPACE_RE.finditer(source_root_tag)
               if match.group(1) not in declared and re.search(rf"[<\s/]{re.escape(match.group(1))}:", text)]
    if not missing:
        return root_tag
    end = len(root_tag) - (2 if root_tag.endswith("/>") else 1)
    return root_tag[:end].rstrip() + "".join(missing) + root_tag[end:]


def _values_dir(path, language=None):
    """Return ``(part index, language, other qualifiers)`` for the ``values-`` directory naming a language.

    A language the tables don't list, like rw, counts when it is ``language``.

    >>> _values_dir("res/values-pt-rBR/strings.xml"), _values_dir("res/values-b+sr+Latn-land/strings.xml")
    ((1, 'pt-BR', []), (1, 'sr-Latn', ['land']))
    >>> _values_dir("res/values-night/strings.xml") is None, _values_dir("res/values-rw/strings.xml", "rw")
    (True, (1, 'rw', []))
    """
    given = language.lower().replace("_", "-").split("-")[0] if language else None
    parts = Path(path).parts
    for part_index in reversed(range(len(parts))):
        qualifiers = parts[part_index].split("-")
        if qualifiers[0] != "values":
            continue
        for index, qualifier in enumerate(qualifiers[1:], start=1):
            if qualifier.startswith("b+"):
                return part_index, "-".join(qualifier[2:].split("+")), qualifiers[1:index] + qualifiers[index + 1:]
            if qualifier.islower() and (_is_language_code(qualifier) or qualifier == given):
                language, end = qualifier, index + 1
                if end < len(qualifiers) and re.fullmatch(r"r[A-Z]{2}", qualifiers[end]):
                    language, end = f"{qualifier}-{qualifiers[end][1:]}", end + 1
                return part_index, language, qualifiers[1:index] + qualifiers[end:]
    return None


def _as_android_reads(text):
    r"""Return text with its references and \u escapes as the characters they stand for, as Android reads it.

    Markup escaped as ``&lt;b>`` is markup to ``Html.fromHtml``, so it's
    checked as that.

    >>> _as_android_reads(r"50&#37; \u0025s \\u0025s &lt;b>&amp;lt; &lt;Untitled&gt;")
    '50% %s \\\\u0025s <b>&lt; &lt;Untitled>'
    """
    # An & stays escaped, as decode_character_references keeps it, so \u0026gt; can't become a tag's end
    text = _UNICODE_ESCAPE_RE.sub(
        lambda match: match.group(1) + chr(int(match.group(2), 16)).replace("&", "&amp;"),
        decode_character_references(text))
    # Android's \n and \t are whitespace, which can end a tag's name as well as a space
    text = _unescape_tags(_WHITESPACE_ESCAPE_RE.sub(
        lambda match: match.group(1) + {"n": "\n", "t": "\t"}[match.group(2)], text))
    return PREDEFINED_ENTITY_RE.sub(lambda match: PREDEFINED_ENTITIES[match.group(1)], text)


def _unescape_tags(text):
    """Return text with each escaped tag, like ``&lt;b>``, as markup: an element Html.fromHtml reads or that
    can run code, or any with an attribute. A word in brackets, like ``&lt;Untitled&gt;``, stays text.

    >>> _unescape_tags("&lt;b>Hi&lt;/b> &lt;Untitled&gt; &lt;x.y hidden onclick=go()>")
    '<b>Hi</b> &lt;Untitled&gt; <x.y hidden onclick=go()>'
    """
    if "&lt;" not in text:
        return text
    # Where each tag can end, and each =, so finding an = before a tag's end takes no rescanning
    ends = [match.start() for match in re.finditer(r">|&gt;", text)]
    equals = [match.start() for match in re.finditer("=", text)]

    def unescape(match):
        after = bisect.bisect_left(ends, match.end())
        end = ends[after] if after < len(ends) else len(text)
        equal = bisect.bisect_left(equals, match.end())
        attribute = equal < len(equals) and equals[equal] < end
        return "<" + match.group(1) if attribute or match.group(1).lstrip("/").lower() in KNOWN_ELEMENTS \
            else match.group()
    return ESCAPED_TAG_START_RE.sub(unescape, text)


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


def _element_text(element, translation, categories, indent, start_tag=None):
    """Write a translated element, like the source's, with ``start_tag`` if the target has one of its own."""
    start_tag = start_tag or element.start_tag
    if element.tag != "plurals":
        return f"{start_tag}{_encode(translation, _decode(element.raw)[1])}</string>"
    # Quoted if any of the source's items is, as a translation may need its spaces kept in every form
    quoted = any(_decode(raw)[1] for raw in element.items.values())
    items = "".join(
        f'{indent * 2}<item quantity="{category}">{_encode(translation[category], quoted)}</item>\n'
        for category in categories if category in translation
    )
    return f"{start_tag}\n{items}{indent}</plurals>"


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
        self.doctype = _doctype(data)


def _doctype(data):
    r"""Return the DOCTYPE declaration, with entities like ``<!ENTITY appname "Notes">``, or ``b""``.

    Found by searching, not a regular expression, so an upload of many
    unfinished declarations takes linear time.

    >>> _doctype(b'<?xml version="1.0"?>\n<!DOCTYPE resources [\n<!ENTITY a "A">\n]>\n<resources/>')
    b'<!DOCTYPE resources [\n<!ENTITY a "A">\n]>'
    >>> _doctype(b"<resources/>"), _doctype(b"<!DOCTYPE [" * 3)
    (b'', b'')
    >>> _doctype(b'<!DOCTYPE resources [<!ENTITY a "[x]"><!-- ] -->]><resources/>')
    b'<!DOCTYPE resources [<!ENTITY a "[x]"><!-- ] -->]>'
    >>> _doctype(b'<!-- <!DOCTYPE resources SYSTEM "x.dtd"> --><resources/>')
    b''
    """
    # Only where XML allows one, before the root element, and not in a comment, which may quote one
    start = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    while match := PROLOG_ITEM_RE.match(data, start):
        start = match.end()
    start = len(data) - len(data[start:].lstrip())
    if not data.startswith(b"<!DOCTYPE", start):
        return b""
    end = data.find(b">", start)
    subset = data.find(b"[", start, end if end >= 0 else len(data))
    if subset >= 0:
        # The internal subset, [...], may hold ">" and, in quotes or comments, "]"; the declaration ends
        # at the first ">" after the "]" that closes it
        close = _subset_end(data, subset + 1)
        end = data.find(b">", close) if close >= 0 else -1
    return data[start:end + 1] if end >= 0 else b""


def _entities(doctype):
    """Return ``{name: declaration}`` for the entities a DOCTYPE declares.

    >>> _entities(b'<!DOCTYPE resources [<!ENTITY app "Notes"> <!ENTITY co "Acme">]>')
    {b'app': b'<!ENTITY app "Notes">', b'co': b'<!ENTITY co "Acme">'}
    """
    return {match.group(1): match.group() for match in ENTITY_RE.finditer(doctype)}


def _with_entities(doctype, declarations):
    """Return a DOCTYPE with ``declarations`` added at the end of its internal subset, making one if it has none.

    >>> _with_entities(b"<!DOCTYPE resources>", b'<!ENTITY a "A">')
    b'<!DOCTYPE resources [<!ENTITY a "A">]>'
    >>> _with_entities(b'<!DOCTYPE resources [<!ENTITY b "B">]>', b'<!ENTITY a "A">')
    b'<!DOCTYPE resources [<!ENTITY b "B"><!ENTITY a "A">]>'
    """
    subset = doctype.find(b"[")
    if subset < 0:
        return doctype[:-1].rstrip() + b" [" + declarations + b"]>"
    close = _subset_end(doctype, subset + 1)
    return doctype[:close] + declarations + doctype[close:]


def _subset_end(data, index):
    """Return where the DOCTYPE's internal subset starting at ``index`` ends, at its "]", or -1."""
    while index < len(data):
        if data[index:index + 1] in (b'"', b"'"):
            index = data.find(data[index:index + 1], index + 1)
        elif data.startswith(b"<!--", index):
            index = data.find(b"-->", index + 4)
        elif data[index:index + 1] == b"]":
            return index
        if index < 0:
            return -1
        index += 1
    return -1


def _read(path):
    if not os.path.exists(path):
        return _Resources()
    with open(path, "rb") as f:
        data = f.read()
    # An empty file, as an editor or touch makes, is a target with nothing in it yet
    if not data.strip():
        return _Resources()
    # Read as bytes, assumed to be UTF-8, as Android's own tools require
    if to_utf8(data, path)[1]:
        raise ValueError(f"{path} is not UTF-8, which Android resource files must be")
    resources = _Resources(data)
    parser = expat.ParserCreate("utf-8")
    stack = []
    pending_comment = []

    def start(tag, attrs):
        start_index = parser.CurrentByteIndex
        # Only the root, the resources and their plural items are kept. Finding where every nested
        # element's tag ends would be slow for those from an entity, each placed at its reference.
        if len(stack) > 2 or (len(stack) == 2 and stack[1][0] != "plurals"):
            stack.append((tag, attrs, None))
            return
        if not data.startswith(b"<", start_index):
            raise ValueError(f"{path} has a resource from an entity, which can't be translated where it is")
        inner_start = tag_end(data, start_index)
        if not stack:
            resources.root_start_tag = data[start_index:inner_start].decode()
            resources.root_start, resources.root_tag_end = start_index, inner_start
        elif len(stack) == 1 and tag in ("string", "plurals"):
            # Strings marked translatable="false" are kept too: in a target they mustn't be added again
            comment = pending_comment.pop() if pending_comment else ""
            element = _Element(tag, attrs.get("name", ""), start_index, data[start_index:inner_start].decode(),
                               comment, translatable=attrs.get("translatable") != "false")
            if not resources.elements and line_indent(data, start_index):
                resources.indent = line_indent(data, start_index).decode()
            resources.elements[f"{tag}/{element.name}"] = element
        if len(stack) == 1:
            pending_comment.clear()
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
        parent = stack[0][0] if len(stack) == 1 else stack[1][0]
        if len(stack) == 1:
            element = resources.elements.get(f"{tag}/{attrs.get('name', '')}")
            if element:
                element.raw, element.end = raw, element_end
        elif len(stack) == 2 and tag == "item" and parent == "plurals":
            element = resources.elements.get(f"plurals/{stack[1][1].get('name', '')}")
            if element:
                element.items[attrs.get("quantity", "other")] = raw

    def comment(text):
        if len(stack) == 1:
            pending_comment[:] = [" ".join(text.split())]

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = comment
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{path} is not valid XML: {e}") from e
    # Only elements that were read in full count; resources without a name can't be matched
    resources.elements = {key: element for key, element in resources.elements.items() if element.name}
    return resources
