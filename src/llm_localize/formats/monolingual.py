"""Base class for formats that keep each language's messages in a file of its own.

JSON, Android and iOS projects write the source language in one file,
like ``locales/en.json``, and each translation in another, like
``locales/fr.json``. Translating ``fr.json`` reads the messages from
``en.json`` and fills in those ``fr.json`` lacks, creating it if needed.
"""
import abc
from dataclasses import dataclass
from functools import cached_property

from llm_localize.formats.base import TranslationFile
from llm_localize.languages import LANGUAGE_NAMES
from llm_localize.plurals import has_rules


@dataclass
class Message:
    """A message in one language's file.

    :param text: the text, for a message without plurals
    :param context: a comment or key that helps translate it
    """

    text: str = ""
    context: str = ""


class MonolingualFile(TranslationFile):
    """A target-language file, translated from the source-language file beside it.

    Subclasses read a file into ``{key: Message}`` with ``read_messages``,
    and implement ``apply`` and ``save`` to write the target file.
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
        return self._language

    @cached_property
    def source_path(self):
        if self._source_path:
            return str(self._source_path)
        raise ValueError(
            f"Can't find the {self.source_language} file to translate {self.path} from; "
            "pass it with --source")


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
