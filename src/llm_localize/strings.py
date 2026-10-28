"""Translate a list of strings at runtime, e.g. user content in a web app."""
from collections import Counter
from dataclasses import dataclass, field

from llm_localize.formats.base import TranslationFile
from llm_localize.units import TranslationUnit


class StringList(TranslationFile):
    """An in-memory "file" holding strings to translate.

    Repeated strings are translated once. Blank strings are left as they are.
    """

    name = "strings"

    def __init__(self, texts, context=""):
        super().__init__("<strings>")
        self.texts = list(texts)
        self.context = context
        self.translations = {}

    def untranslated_units(self):
        unique = dict.fromkeys(text for text in self.texts if text.strip())
        return [TranslationUnit(key=text, source=text, context=self.context) for text in unique]

    def apply(self, key, translation):
        self.translations[key] = translation

    def save(self):
        pass

    def results(self):
        return [text if not text.strip() else self.translations.get(text) for text in self.texts]


@dataclass
class StringsResult:
    """Translations for a list of strings, in the same order.

    :ivar translations: one per input string; ``None`` where no valid
        translation came back
    :ivar rejected: ``Counter`` of reasons translations were rejected
    :ivar errors: ``Counter`` of error messages from failed batches
    """

    translations: list
    rejected: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)

    @property
    def complete(self):
        return None not in self.translations
