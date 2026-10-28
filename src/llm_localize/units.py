"""Format-neutral description of a message that needs translating."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PluralForm:
    """One plural form of the target language.

    :param index: the form's index in the file format, e.g. N in ``msgstr[N]``
    :param description: which counts use it, e.g. "used when n is 2, 3, 4"
    :param singular: True if only n == 1 uses this form. Its translation
        is validated against the singular source, every other form's
        against the plural source.
    """

    index: int
    description: str
    singular: bool = False


@dataclass(frozen=True)
class TranslationUnit:
    """A message to translate.

    :param key: identifies the message within its file; formats choose
        what it is and get it back in ``TranslationFile.apply``
    :param source: the text to translate (the singular, for plurals)
    :param plural_source: the plural text; empty for non-plural messages
    :param plural_forms: the target language's plural forms; empty for
        non-plural messages
    :param context: disambiguating context or translator comments
    """

    key: str
    source: str
    plural_source: str = ""
    plural_forms: tuple[PluralForm, ...] = ()
    context: str = ""

    @property
    def is_plural(self):
        return bool(self.plural_source)
