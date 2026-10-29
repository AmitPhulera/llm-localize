"""Base class for formats that keep each language's messages in a file of its own.

JSON, Android and iOS projects write the source language in one file,
like ``locales/en.json``, and each translation in another, like
``locales/fr.json``. Translating ``fr.json`` reads the messages from
``en.json`` and fills in those ``fr.json`` lacks, creating it if needed.
"""
import abc
import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from llm_localize.formats.base import TranslationFile
from llm_localize.languages import LANGUAGE_NAMES, to_locale
from llm_localize.plurals import has_rules, plural_categories, plural_forms
from llm_localize.units import TranslationUnit


@dataclass
class Message:
    """A message in one language's file.

    :param text: the text, for a message without plurals
    :param plurals: ``{CLDR category: text}``, for a plural message
    :param context: a comment or key that helps translate it
    :param translatable: False for a message marked not to be translated,
        which is skipped in the source and counts as done in the target
    """

    text: str = ""
    plurals: dict = field(default_factory=dict)
    context: str = ""
    translatable: bool = True


class MonolingualFile(TranslationFile):
    """A target-language file, translated from the source-language file beside it.

    Subclasses read a file into ``{key: Message}`` with ``read_messages``,
    and implement ``apply`` and ``save`` to write the target file.
    Translations of plural messages are ``{CLDR category: text}``.
    """

    def __init__(self, path, language=None, source_language="en", source_path=None):
        super().__init__(path)
        self._language = language
        self.source_language = source_language or "en"
        self._source_path = source_path

    @classmethod
    def open(cls, path, language=None, source_language=None, source_path=None):
        return cls(path, language=language, source_language=source_language, source_path=source_path)

    @abc.abstractmethod
    def read_messages(self, path):
        """Return ``{key: Message}`` for the file at ``path``, in file order; ``{}`` if it doesn't exist."""

    @cached_property
    def language(self):
        return self._language or self.language_from_path()

    def language_from_path(self):
        """Return the language code in the file's path, or None."""
        match = self._language_in_path()
        return match[2] if match else None

    @cached_property
    def source_path(self):
        if self._source_path:
            # A missing one would read as a file with nothing in it, so nothing would be translated
            if not os.path.isfile(self._source_path):
                raise ValueError(f"The source file {self._source_path} doesn't exist")
            return str(self._source_path)
        for candidate in self.source_path_candidates():
            if os.path.isfile(candidate):
                return str(candidate)
        raise ValueError(
            f"Can't find the {self.source_language} file to translate {self.path} from; "
            "pass it with --source")

    def source_path_candidates(self):
        """Yield paths the source file might have, with the language in the path swapped for the source's."""
        match = self._language_in_path()
        if not match:
            return
        part_index, token_index, _ = match
        parts = list(Path(self.path).parts)
        tokens = parts[part_index].split(".")
        for spelling in dict.fromkeys([self.source_language, to_locale(self.source_language),
                                       self.source_language.lower(), self.source_language.split("-")[0]]):
            tokens[token_index] = spelling
            parts[part_index] = ".".join(tokens)
            yield Path(*parts)

    def _language_in_path(self):
        """Return ``(part index, token index, code)`` for the language code in the path, or None.

        Looks at the file name first, then its directories, splitting each
        on dots, so ``fr.json``, ``messages.fr.json`` and ``fr/app.json``
        all name French. With an explicit language, only that language counts.
        Directories above the current one aren't searched, so a project in
        ``/home/de/`` isn't taken for German. For a path outside the current
        directory, only its last four parts are, so ``/srv/de/notes.md`` is
        German; pass the language to be sure.
        """
        parts = Path(self.path).parts
        for part_index in reversed(range(_first_searched_part(self.path), len(parts))):
            for token_index, token in enumerate(parts[part_index].split(".")):
                if self._language:
                    matches = _base(token) == _base(self._language) and _is_language_code(token, known=False)
                else:
                    matches = _is_language_code(token)
                if matches:
                    return part_index, token_index, token
        return None

    @property
    def is_source(self):
        """True if this is the source file itself, as when a glob matches it too."""
        return os.path.exists(self.path) and os.path.samefile(self.path, self.source_path)

    @cached_property
    def source_messages(self):
        return self.read_messages(self.source_path)

    @cached_property
    def target_messages(self):
        return self.read_messages(self.path)

    @cached_property
    def plural_forms(self):
        return plural_forms(self.language)

    @property
    def plural_categories(self):
        return list(plural_categories(self.language))

    def untranslated_units(self):
        if self.is_source:
            return []
        units = []
        for key, message in self.source_messages.items():
            if self.is_translated(message, self.target_messages.get(key)):
                continue
            if message.plurals:
                other = message.plurals.get("other") or next(iter(message.plurals.values()))
                units.append(TranslationUnit(
                    key=key, source=message.plurals.get("one", other), plural_source=other,
                    plural_forms=self.plural_forms, context=message.context,
                ))
            else:
                units.append(TranslationUnit(key=key, source=message.text, context=message.context))
        return units

    def with_translated_forms(self, key, translation):
        """Return a plural translation with the forms the target already translates kept, not replaced.

        A partly translated plural, like one with ``one`` and ``other`` in
        Russian but no ``few`` or ``many``, is translated again to fill in
        the rest, and the forms someone already wrote stay.
        """
        target = self.target_messages.get(key)
        if not isinstance(translation, dict) or not target:
            return translation
        return {**translation, **{category: text for category, text in target.plurals.items() if text.strip()}}

    def is_translated(self, message, target):
        """True if the target's ``target`` message translates the source's ``message``, or it needn't."""
        if not message.translatable or (target and not target.translatable):
            return True
        if message.plurals:
            return bool(target) and all(target.plurals.get(form.index, "").strip() for form in self.plural_forms)
        return not message.text.strip() or bool(target and target.text.strip())


def _first_searched_part(path):
    """Return the index of the first part of ``path`` to look for a language in.

    That's the first part below the current directory, or for a path
    outside it, the fourth from the end, whether it's given relative or absolute.
    """
    parts = Path(path).parts
    relative = os.path.relpath(os.path.realpath(path), os.path.realpath(os.getcwd()))
    if relative.startswith(os.pardir):
        return max(0, len(parts) - 4)
    return max(0, len(parts) - len(Path(relative).parts))


def _base(code):
    return code.lower().replace("_", "-").split("-")[0]


def _is_language_code(token, known=True):
    """Return True if ``token`` looks like a language code or locale name we know, like fr, pt_BR or zh-Hans.

    After the language, only a script and a region may follow, so a
    file named ``to_trans`` isn't taken for Tongan. With ``known`` False,
    any two- or three-letter language counts, like rw for Kinyarwanda,
    which neither Django nor CLDR's plural rules list.

    >>> [_is_language_code(t) for t in ["fr", "pt_BR", "zh-Hans", "en-US", "es-419", "sr-Latn-RS"]]
    [True, True, True, True, True, True]
    >>> [_is_language_code(t) for t in ["json", "messages", "app", "to_trans", "my_notes", "en-US-x"]]
    [False, False, False, False, False, False]
    >>> _is_language_code("rw"), _is_language_code("rw", known=False), _is_language_code("en-guide", known=False)
    (False, True, False)
    """
    base, *subtags = token.lower().replace("_", "-").split("-")
    if not 2 <= len(base) <= 3 or not base.isalpha():
        return False
    if known and base not in LANGUAGE_NAMES and not has_rules(base):
        return False
    if subtags and len(subtags[0]) == 4 and subtags[0].isalpha():
        subtags = subtags[1:]  # the script, like Hans
    return not subtags or (len(subtags) == 1 and (
        (len(subtags[0]) == 2 and subtags[0].isalpha()) or (len(subtags[0]) == 3 and subtags[0].isdigit())))
