"""Helpers for XML formats that edit their files in place by byte offsets."""
import re

# An & that doesn't start an entity like &amp; or &#8230;
BARE_AMPERSAND_RE = re.compile(r"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")


def open_tag(start_tag):
    """Return a start tag that closes itself, like ``<x/>``, as an opening one, ``<x>``; any other as it is.

    >>> open_tag("<x a='1' />"), open_tag(b"<x>")
    ("<x a='1'>", b'<x>')
    """
    slash, end = ("/", ">") if isinstance(start_tag, str) else (b"/", b">")
    return start_tag[:-2].rstrip() + end if start_tag.endswith(slash + end) else start_tag


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

