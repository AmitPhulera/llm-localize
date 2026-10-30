"""iOS and macOS strings: ``.strings`` files, one per language.

``fr.lproj/Localizable.strings`` is translated from ``en.lproj`` beside
it; new entries are added at its end and empty ones filled in place,
keeping the rest of the file and its encoding.
"""
import codecs
import os
import re
from functools import cached_property

from llm_localize.formats.base import splice, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile

INSTRUCTIONS = (
    "Messages are Apple strings, and each one's context gives its key or comment. Keep format "
    "specifiers like %@, %d, %lld and %1$@ exactly as they are."
)

TOKEN_RE = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<word>[^\s=;"/]+)
  | (?P<punct>[=;])
""", re.S | re.X)

BOMS = {"utf-8-sig": codecs.BOM_UTF8, "utf-16-le": codecs.BOM_UTF16_LE, "utf-16-be": codecs.BOM_UTF16_BE}

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


class StringsFile(MonolingualFile):
    name = "strings"
    extensions = (".strings",)
    instructions = INSTRUCTIONS

    def read_messages(self, path):
        messages = {}
        for entry in _read_strings(path)[1]:
            context = "; ".join(filter(None, [entry["comment"], "" if entry["key"] == entry["value"]
                                              else f"Key: {entry['key']}"]))
            messages[entry["key"]] = Message(text=entry["value"], context=context)
        return messages

    @cached_property
    def _applied(self):
        return {}

    def apply(self, key, translation):
        self._applied[key] = translation

    @cached_property
    def _source_strings(self):
        """The source file's text, entries and encoding, read once rather than at every save."""
        return _read_strings(self.source_path)

    def save(self):
        """Write the target file: its original text, with empty values filled and new entries added at the end."""
        text, entries, encoding = _read_strings(self.path)
        _, source_entries, source_encoding = self._source_strings
        if not os.path.exists(self.path):
            encoding = source_encoding
        existing = {entry["key"]: entry for entry in entries}
        comments = {entry["key"]: entry["comment"] for entry in source_entries}
        replacements, additions = [], []
        for key, translation in self._applied.items():
            if key in existing:
                replacements.append((*existing[key]["value_span"], _quote(translation)))
            else:
                # A comment holding */, which a // comment may, can't be written as /* ... */
                comment = comments.get(key, "")
                comment = f"// {comment}\n" if "*/" in comment else f"/* {comment} */\n" if comment else ""
                additions.append(f"\n{comment}{_quote(key)} = {_quote(translation)};\n")
        addition = "".join(additions)
        if not text:
            addition = addition.lstrip("\n")
        elif addition and not text.endswith("\n"):
            addition = "\n" + addition
        replacements.append((len(text), len(text), addition))
        write_file(self.path, _encode_file(splice(text, replacements), encoding))


def _starts_line(text, index):
    """True if only spaces come before ``index`` on its line."""
    return not text[text.rfind("\n", 0, index) + 1:index].strip()


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
            words = " ".join(value.strip("/*").split())
            if not _starts_line(text, tokens[index][2][0]):
                # After an entry on its line, it's that entry's
                comment = ""
            elif index and value.startswith("//") and tokens[index - 1][1].startswith("//") \
                    and _starts_line(text, tokens[index - 1][2][0]):
                # Lines of // comments run on, as one comment
                comment = f"{comment} {words}"
            else:
                comment = words
            index += 1
            continue
        parts = tokens[index:index + 4]
        if (len(parts) < 4 or parts[0][0] not in ("string", "word") or parts[1][1] != "="
                or parts[2][0] != "string" or parts[3][1] != ";"):
            raise ValueError(f"{path} is not a valid .strings file near {value[:40]!r}")
        try:
            key = _unquote(parts[0][1]) if parts[0][0] == "string" else parts[0][1]
            entries.append({"key": key, "value": _unquote(parts[2][1]), "comment": comment,
                            "value_span": parts[2][2]})
        except ValueError as e:
            raise ValueError(f"{path} is not a valid .strings file near {value[:40]!r}: {e}") from e
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
            if len(escape) == 1:
                raise ValueError(f"\\{escape} is not followed by four hex digits")
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
