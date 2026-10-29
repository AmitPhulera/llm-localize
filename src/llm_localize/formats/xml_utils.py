"""Helpers for XML formats that edit their files in place by byte offsets."""
import re
from collections import Counter

# A character reference, like &#37; or &#x25;
CHARACTER_REFERENCE_RE = re.compile(r"&#(\d{1,8}|[xX][0-9A-Fa-f]{1,8});")

# An & that doesn't start an entity like &amp; or &#8230;
BARE_AMPERSAND_RE = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
# A tag, like <b>, </b> or <x id="1"/>
TAG_RE = re.compile(r"<[^<>]+>")


def open_tag(start_tag):
    """Return a start tag that closes itself, like ``<x/>``, as an opening one, ``<x>``; any other as it is.

    >>> open_tag("<x a='1' />"), open_tag(b"<x>")
    ("<x a='1'>", b'<x>')
    """
    slash, end = ("/", ">") if isinstance(start_tag, str) else (b"/", b">")
    return start_tag[:-2].rstrip() + end if start_tag.endswith(slash + end) else start_tag


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
