"""Android string resources: ``res/values/strings.xml`` and its translations, like ``res/values-fr/strings.xml``.
"""
import re
from pathlib import Path

from llm_localize.formats.monolingual import _is_language_code
from llm_localize.formats.xml_utils import BARE_AMPERSAND_RE

# A CDATA section, whose & needn't be escaped, or a tag
CDATA_OR_TAG_RE = re.compile(r"(<!\[CDATA\[.*?\]\]>|<[^>]*>)", re.S)
# Not escaped: after no backslash, or after escaped ones, whose run is kept as group 1, as in "C:\\"
UNESCAPED = r"(?<!\\)((?:\\\\)*)"
UNESCAPED_QUOTE_RE = re.compile(UNESCAPED + '"')
UNESCAPED_APOSTROPHE_RE = re.compile(UNESCAPED + "'")
# An escaped quote or apostrophe
ESCAPED_QUOTE_RE = re.compile(UNESCAPED + r"\\(['\"])")


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
