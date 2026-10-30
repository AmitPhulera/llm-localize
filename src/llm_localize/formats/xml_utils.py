"""Helpers for XML formats that edit their files in place by byte offsets."""
import codecs
import re
from collections import Counter

# An attribute, its value in quotes, so text in one isn't taken for another
ATTRIBUTE_RE = re.compile(rb'''\s([^\s=/>]+)\s*=\s*("[^"]*"|'[^']*')''')
# A character reference, like &#37; or &#x25;
CHARACTER_REFERENCE_RE = re.compile(r"&#(\d{1,8}|[xX][0-9A-Fa-f]{1,8});")

# An & that doesn't start an entity like &amp; or &#8230;
BARE_AMPERSAND_RE = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
DECLARED_ENCODING_RE = re.compile(rb"""<\?xml[^>]*?\sencoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")
# The printable ASCII characters
ASCII = bytes(range(0x20, 0x7F)).decode()
BOMS = {codecs.BOM_UTF16_LE: "utf-16-le", codecs.BOM_UTF16_BE: "utf-16-be"}
# A tag, like <b>, </b> or <x id="1"/>
TAG_RE = re.compile(r"<[^<>]+>")


def open_tag(start_tag):
    """Return a start tag that closes itself, like ``<x/>``, as an opening one, ``<x>``; any other as it is.

    >>> open_tag("<x a='1' />"), open_tag(b"<x>")
    ("<x a='1'>", b'<x>')
    """
    slash, end = ("/", ">") if isinstance(start_tag, str) else (b"/", b">")
    return start_tag[:-2].rstrip() + end if start_tag.endswith(slash + end) else start_tag


def set_attribute(start_tag, name, value):
    """Return a start tag with attribute ``name`` set to ``value``, added if it isn't there.

    Attributes are read in turn, so text in another's quoted value isn't taken for one.

    >>> set_attribute(b"<t note=' state=x' state='new'/>", b"state", b"translated")
    b"<t note=' state=x' state='translated'/>"
    >>> set_attribute(b"<t>", b"state", b"translated")
    b'<t state="translated">'
    """
    found = next((match for match in ATTRIBUTE_RE.finditer(start_tag) if match.group(1) == name), None)
    if found:
        start, end = found.span(2)
        return start_tag[:start + 1] + value + start_tag[end - 1:]
    end = -2 if start_tag.endswith(b"/>") else -1
    return start_tag[:end] + b" " + name + b'="' + value + b'"' + start_tag[end:]


def changes_tags(source, translation, counted=True):
    """True if a translation's tags aren't the source's, exactly and as many times, in any order.

    The HTML check lower-cases names, so <X ID="1"/> would pass for <x id="1"/>.
    Without ``counted``, as for an ICU message whose translation has more
    plural cases, each tag only has to be there.

    >>> changes_tags('Hi <x id="N"/>', 'Salut <x id="N"/>'), changes_tags('Hi <x id="N"/>', 'Salut <X ID="N"/>')
    (False, True)
    >>> changes_tags('<x id="A"/> <x id="B"/> <x id="A"/>', '<x id="B"/> <x id="A"/> <x id="B"/>')
    True
    """
    kind = Counter if counted else set
    return kind(TAG_RE.findall(source)) != kind(TAG_RE.findall(translation))


def to_utf8(data, path):
    """Return ``(UTF-8 data, encoding, BOM)`` for an XML document's bytes, and how to write them back.

    A UTF-8 document comes back as it is, with ``encoding`` None.
    Others, like UTF-16, are decoded, so byte offsets and text are UTF-8
    either way; parse the result with ``expat.ParserCreate("UTF-8")``, as
    its declaration still names the original encoding.

    >>> to_utf8('<?xml version="1.0" encoding="UTF-16"?><a>é</a>'.encode("utf-16"), "x.xml")[1:]
    ('utf-16-le', b'\xff\xfe')
    >>> to_utf8(b'<a/>', "x.xml")
    (b'<a/>', None, b'')
    """
    bom = next((bom for bom in BOMS if data.startswith(bom)), b"")
    if bom:
        encoding = BOMS[bom]
    elif data.startswith(b"<\0?\0"):
        encoding = "utf-16-le"
    elif data.startswith(b"\0<\0?"):
        encoding = "utf-16-be"
    else:
        match = DECLARED_ENCODING_RE.match(data)
        encoding = match.group(1).decode().lower() if match else "utf-8"
    try:
        name = codecs.lookup(encoding).name
        if name == "utf-8":
            return data, None, b""
        # A character encoding writes ASCII as ASCII, or is UTF-16 or UTF-32. Python's other codecs, like
        # punycode or unicode-escape, aren't, and some decode in quadratic time.
        if not name.startswith(("utf-16", "utf-32")) and ASCII.encode(name) != ASCII.encode():
            raise ValueError(f"{path} has an encoding XML can't be in, {encoding!r}")
        return data[len(bom):].decode(encoding).encode(), encoding, bom
    except LookupError as e:
        raise ValueError(f"{path} has an unknown encoding {encoding!r}") from e
    except UnicodeError as e:
        raise ValueError(f"{path} is not valid {encoding}: {e}") from e


def from_utf8(data, encoding, bom):
    """Return UTF-8 ``data`` in the encoding ``to_utf8`` found, with character references where it falls short."""
    if not encoding:
        return data
    return bom + data.decode().encode(encoding, "xmlcharrefreplace")


def tag_end(data, start):
    """Return the index just past the ``>`` closing the tag at ``start``, skipping quoted attribute values.

    >>> tag_end(b'<a title="x>y">text</a>', 0)
    15
    """
    quote = None
    for index in range(start, len(data)):
        char = data[index:index + 1]
        if quote:
            if char == quote:
                quote = None
        elif char in (b'"', b"'"):
            quote = char
        elif char == b">":
            return index + 1
    raise ValueError("unterminated tag")


def line_indent(data, start):
    """Return the whitespace before ``start`` on its line, or ``b""`` if something else comes first."""
    # Only back over the spaces before it, so files on one long line aren't rescanned for every element
    index = start
    while index and data[index - 1:index].isspace() and data[index - 1:index] != b"\n":
        index -= 1
    return data[index:start] if index == 0 or data[index - 1:index] == b"\n" else b""


def decode_character_references(text):
    """Return text with character references like ``&#37;`` as the characters they stand for, as XML reads them.

    An ``&`` stays escaped, so ``&#38;gt;``, text that reads "&gt;", can't
    be taken for ``&gt;`` when entities are replaced after.

    >>> decode_character_references("50&#37; &#x41;&amp; &#0; &#99999999; &#38;gt;")
    '50% A&amp; &#0; &#99999999; &amp;gt;'
    """
    def character(match):
        number = int(match.group(1)[1:], 16) if match.group(1)[:1] in "xX" else int(match.group(1))
        return ("&amp;" if number == 38 else chr(number)) if 0 < number <= 0x10FFFF else match.group()
    return CHARACTER_REFERENCE_RE.sub(character, text)
