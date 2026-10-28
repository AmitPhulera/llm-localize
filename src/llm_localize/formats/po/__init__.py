"""gettext PO files."""
from functools import cached_property
from pathlib import Path

import polib

from llm_localize.formats.base import TranslationFile
from llm_localize.formats.po.cleanup import entry_has_control_chars, save_po
from llm_localize.formats.po.plurals import counts_by_plural_index_from_header, nplurals_from_header
from llm_localize.units import PluralForm, TranslationUnit

LC_MESSAGES = "LC_MESSAGES"


class PoFile(TranslationFile):
    """A gettext PO file.

    Untranslated, fuzzy and corrupted (control character) entries are
    translated. Obsolete (``#~``) entries are skipped. Plural forms come
    from the ``Plural-Forms`` header.
    """

    @cached_property
    def po(self):
        return polib.pofile(self.path)

    @property
    def language(self):
        """Return the ``Language`` header, or the locale of ``<locale>/LC_MESSAGES/x.po``."""
        language = self.po.metadata.get("Language", "").strip()
        if language:
            return language
        parent = Path(self.path).parent
        if parent.name == LC_MESSAGES:
            return parent.parent.name
        return None

    @cached_property
    def _plural_forms_header(self):
        return self.po.metadata.get("Plural-Forms", "")

    @cached_property
    def nplurals(self):
        return nplurals_from_header(self._plural_forms_header)

    @cached_property
    def plural_forms(self):
        counts_by_plural_index = counts_by_plural_index_from_header(self._plural_forms_header)
        return tuple(
            PluralForm(index=index, description=_describe_counts(counts), singular=counts == [1])
            for index, counts in counts_by_plural_index.items()
        )

    @cached_property
    def _entries(self):
        return {str(index): entry for index, entry in enumerate(self.po)}

    def untranslated_units(self):
        return [
            self._unit(key, entry)
            for key, entry in self._entries.items()
            if not entry.obsolete
            and (entry.fuzzy or not self._is_translated(entry) or entry_has_control_chars(entry))
        ]

    def _is_translated(self, entry):
        if entry.msgid_plural:
            return all(entry.msgstr_plural.get(index) for index in range(self.nplurals))
        return entry.msgstr != ""

    def _unit(self, key, entry):
        context = "\n".join(filter(None, [entry.msgctxt, entry.comment]))
        if entry.msgid_plural:
            return TranslationUnit(
                key=key,
                source=entry.msgid,
                plural_source=entry.msgid_plural,
                plural_forms=self.plural_forms,
                context=context,
            )
        return TranslationUnit(key=key, source=entry.msgid, context=context)

    def apply(self, key, translation):
        entry = self._entries[key]
        if entry.msgid_plural:
            # Replace every plural index, including ones already translated:
            # a partly translated entry usually means the Plural-Forms header
            # gained an index, which can change what the existing ones mean
            entry.msgstr_plural = dict(translation)
        else:
            entry.msgstr = translation

    def save(self):
        save_po(self.po)


def _describe_counts(counts):
    if not counts:
        return "not used for whole numbers (e.g. fractions); use the general plural"
    examples = ", ".join(str(n) for n in counts[:8])
    return f"used when n is {examples}{', ...' if len(counts) > 8 else ''}"
