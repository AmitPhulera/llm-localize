"""iOS and macOS strings: ``.strings`` files, one per language, and Xcode's ``.xcstrings`` string catalogs.

``fr.lproj/Localizable.strings`` is translated from ``en.lproj`` (or
``Base.lproj``) beside it; new entries are added at its end and empty
ones filled in place, keeping the rest of the file and its encoding. An
``.xcstrings`` catalog holds every language, so it's translated for one
``--lang`` at a time, like a PO file. Plural variations are translated
by CLDR category; entries with device variations or substitutions, and
``.stringsdict`` files, are left alone.
"""
import codecs
import json
import os
import re
from functools import cached_property
from pathlib import Path

from llm_localize.formats.base import TranslationFile, load_json, splice, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.plurals import plural_categories, plural_forms
from llm_localize.units import TranslationUnit

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

    def source_path_candidates(self):
        candidates = list(super().source_path_candidates())
        yield from candidates
        # Base.lproj, beside the language's .lproj directory
        for candidate in candidates[:1]:
            parts = list(candidate.parts)
            for index, part in enumerate(parts):
                if part.endswith(".lproj"):
                    parts[index] = "Base.lproj"
                    yield Path(*parts)

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


class XcstringsFile(TranslationFile):
    """An Xcode string catalog, translated for one language at a time."""

    name = "xcstrings"
    extensions = (".xcstrings",)
    instructions = INSTRUCTIONS

    def __init__(self, path, language=None):
        super().__init__(path)
        self._language = language

    @classmethod
    def open(cls, path, language=None, source_language=None, source_path=None):
        return cls(path, language=language)

    @cached_property
    def language(self):
        """The language to translate to, spelled as the catalog spells it, or as Xcode would, like ``pt-BR``."""
        if not self._language:
            return None
        wanted = _bcp47(self._language).lower()
        for entry in self.document.get("strings", {}).values():
            for code in entry.get("localizations", {}):
                if _bcp47(code).lower() == wanted:
                    return code
        return _bcp47(self._language)

    @cached_property
    def document(self):
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self._ending = "\n" if text.endswith("\n") else ""
        document = load_json(text, self.path)
        _check_catalog(document, self.path)
        return document

    @property
    def source_language(self):
        return self.document.get("sourceLanguage", "en")

    def untranslated_units(self):
        if not self.language:
            raise ValueError(f"{self.path} holds every language; pass the one to translate to with --lang")
        if _bcp47(self.language).lower() == _bcp47(self.source_language).lower():
            raise ValueError(f"{self.language} is the source language of {self.path}; "
                             "pass the one to translate to")
        forms = plural_forms(self.language)
        units = []
        for key, entry in self.document.get("strings", {}).items():
            if entry.get("shouldTranslate") is False:
                continue
            source = entry.get("localizations", {}).get(self.source_language, {})
            target = entry.get("localizations", {}).get(self.language, {})
            context = "; ".join(filter(None, [entry.get("comment", ""), f"Key: {key}"]))
            # A target in a shape this can't write back, like device variations, would be lost
            if "substitutions" in target or ("variations" in target and _plural_units(target) is None):
                continue
            if "variations" in source:
                # Only plural variations; device variations nest theirs inside
                plurals = _plural_units(source)
                if plurals is None:
                    continue
                translated = _plural_units(target) or {}
                if all(_is_translated(translated.get(form.index, {})) for form in forms):
                    continue
                plurals = {category: unit.get("value", "") for category, unit in plurals.items()}
                other = plurals.get("other", key)
                units.append(TranslationUnit(key=key, source=plurals.get("one", other), plural_source=other,
                                             plural_forms=forms, context=context))
            elif "substitutions" not in source and "variations" not in target:
                text = source.get("stringUnit", {}).get("value", key)
                if text.strip() and not _is_translated(target.get("stringUnit", {})):
                    units.append(TranslationUnit(key=key, source=text, context=context))
        return units

    def apply(self, key, translation):
        localizations = self.document["strings"][key].setdefault("localizations", {})
        if isinstance(translation, dict):
            # Forms already translated stay as they are; the rest are filled in
            existing = (localizations.get(self.language, {}).get("variations") or {}).get("plural") or {}
            done = {category for category, variation in existing.items()
                    if _is_translated(variation.get("stringUnit", {}))}
            plural = {category: existing[category] if category in done
                      else {"stringUnit": {"state": "translated", "value": translation[category]}}
                      for category in plural_categories(self.language) if category in translation}
            localizations[self.language] = {"variations": {"plural": plural}}
        else:
            localizations[self.language] = {"stringUnit": {"state": "translated", "value": translation}}
        # Xcode keeps languages in alphabetical order
        self.document["strings"][key]["localizations"] = dict(sorted(localizations.items()))

    def save(self):
        text = json.dumps(self.document, ensure_ascii=False, indent=2, separators=(",", " : "))
        write_file(self.path, (text + self._ending).encode())


def _check_catalog(document, path):
    """Raise ValueError unless the catalog has objects and strings where Xcode writes them."""
    def check(value, kind, where):
        if not isinstance(value, kind):
            raise ValueError(f"{path} is not a valid string catalog: {where} must be "
                             f"{'an object' if kind is dict else 'a string'}")

    def check_localization(localization, where):
        check(localization, dict, where)
        check(localization.get("stringUnit", {}), dict, f"{where} stringUnit")
        check(localization.get("stringUnit", {}).get("value", ""), str, f"{where} stringUnit value")
        check(localization.get("variations", {}), dict, f"{where} variations")
        for kind, cases in localization.get("variations", {}).items():
            check(cases, dict, f"{where} {kind} variations")
            for case, variation in cases.items():
                # Device variations may hold plural ones in turn
                check_localization(variation, f"{where} {kind} variation {case!r}")

    check(document, dict, "the catalog")
    check(document.get("sourceLanguage", ""), str, "sourceLanguage")
    check(document.get("strings", {}), dict, "strings")
    for key, entry in document.get("strings", {}).items():
        check(entry, dict, f"the entry {key!r}")
        check(entry.get("comment", ""), str, f"the comment of {key!r}")
        check(entry.get("localizations", {}), dict, f"the localizations of {key!r}")
        for language, localization in entry.get("localizations", {}).items():
            check_localization(localization, f"the {language} localization of {key!r}")


def _bcp47(code):
    """Return a language code cased as BCP 47 writes it, as Xcode does.

    >>> _bcp47("pt-br"), _bcp47("zh_hans"), _bcp47("sr-latn-rs"), _bcp47("es-419"), _bcp47("FR")
    ('pt-BR', 'zh-Hans', 'sr-Latn-RS', 'es-419', 'fr')
    """
    base, *subtags = code.replace("_", "-").split("-")
    return "-".join([base.lower(), *(tag.title() if len(tag) == 4 else tag.upper() if len(tag) == 2 else tag
                                     for tag in subtags)])


def _plural_units(localization):
    """Return ``{category: stringUnit}`` for a localization's plural variations, or None if it has none.

    None too for plural variations that vary again inside, by device for instance.
    """
    plural = localization.get("variations", {}).get("plural")
    if not isinstance(plural, dict):
        return None
    if any(not isinstance(variation, dict) or variation.keys() - {"stringUnit"} for variation in plural.values()):
        return None
    return {category: variation.get("stringUnit", {}) for category, variation in plural.items()}


def _is_translated(string_unit):
    """True for a stringUnit with a value that isn't in the ``new`` state."""
    return bool(string_unit.get("value", "").strip()) and string_unit.get("state") != "new"


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
