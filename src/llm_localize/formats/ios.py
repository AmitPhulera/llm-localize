"""iOS and macOS strings: ``.strings`` files, one per language."""
import re

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


def _unquote(quoted):
    r"""Decode a quoted .strings value.

    Characters beyond U+FFFF are written as two escapes, a UTF-16
    surrogate pair, which are joined into one character.

    >>> _unquote(r'"Say \"hi\"\nnow \U2026 \UD83D\UDE00"')
    'Say "hi"\nnow … 😀'
    >>> _unquote(r'"\101\12"')
    'A\n'
    """
    def replace(match):
        escape = match.group(1)
        if escape[0] in "uU":
            return chr(int(escape[1:], 16))
        # Octal, as in \101 for "A"
        if escape[0] in "01234567":
            return chr(int(escape, 8))
        return ESCAPES.get(escape, escape)
    text = re.sub(r"\\([uU][0-9A-Fa-f]{4}|[0-7]{1,3}|.)", replace, quoted[1:-1], flags=re.S)
    # A surrogate left without its pair stays one, and _quote writes it back as an escape
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _quote(text):
    r"""Encode text as a quoted .strings value.

    >>> print(_quote('Say "hi"\r\nnow\\'))
    "Say \"hi\"\r\nnow\\"
    """
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
               .replace("\t", "\\t"))
    # Lone surrogates can't be encoded, so they stay escapes, as they were read
    escaped = re.sub("[\ud800-\udfff]", lambda match: f"\\U{ord(match.group()):04X}", escaped)
    return f'"{escaped}"'
