"""iOS and macOS strings: ``.strings`` files, one per language."""
import codecs
import os
import re

TOKEN_RE = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<word>[^\s=;"/]+)
  | (?P<punct>[=;])
""", re.S | re.X)

BOMS = {"utf-8-sig": codecs.BOM_UTF8, "utf-16-le": codecs.BOM_UTF16_LE, "utf-16-be": codecs.BOM_UTF16_BE}

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


def _read_strings(path):
    """Return a ``.strings`` file's text, its entries and its encoding.

    Each entry is a dict of ``key``, ``value``, ``comment`` (the comment
    just before it) and ``value_span``, the value's quoted text's position.
    """
    if not os.path.exists(path):
        return "", [], "utf-8"
    with open(path, "rb") as f:
        data = f.read()
    encoding = _encoding(data)
    text = data[len(BOMS.get(encoding, b"")):].decode(encoding.replace("-sig", ""))
    # One token after another; a search from every position would go on past something like an unfinished
    # comment, rescanning the rest of the file each time
    tokens, position = [], 0
    while position < len(text):
        match = TOKEN_RE.match(text, position)
        if not match:
            raise ValueError(f"{path} is not a valid .strings file")
        if match.lastgroup != "space":
            tokens.append((match.lastgroup, match.group(), match.span()))
        position = match.end()
    entries, comment, index = [], "", 0
    while index < len(tokens):
        kind, value, _ = tokens[index]
        if kind == "comment":
            comment = " ".join(value.strip("/*").split())
            index += 1
            continue
        parts = tokens[index:index + 4]
        if (len(parts) < 4 or parts[0][0] not in ("string", "word") or parts[1][1] != "="
                or parts[2][0] != "string" or parts[3][1] != ";"):
            raise ValueError(f"{path} is not a valid .strings file near {value[:40]!r}")
        key = _unquote(parts[0][1]) if parts[0][0] == "string" else parts[0][1]
        entries.append({"key": key, "value": _unquote(parts[2][1]), "comment": comment, "value_span": parts[2][2]})
        comment = ""
        index += 4
    return text, entries, encoding


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


def _encoding(data):
    """Return a .strings file's encoding: UTF-16 with a byte order mark, or UTF-8 with or without one."""
    for encoding, bom in BOMS.items():
        if data.startswith(bom):
            return encoding
    return "utf-8"


def _encode_file(text, encoding):
    return BOMS.get(encoding, b"") + text.encode(encoding.replace("-sig", ""))
