"""gettext PO files."""
from functools import cached_property
from pathlib import Path

import polib

from llm_localize.formats.base import TranslationFile
from llm_localize.formats.po.cleanup import entry_has_control_chars, save_po
from llm_localize.units import TranslationUnit

LC_MESSAGES = "LC_MESSAGES"


class PoFile(TranslationFile):
    """A gettext PO file.

    Untranslated, fuzzy and corrupted (control character) entries are
    translated. Obsolete (``#~``) entries are skipped.
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
        return entry.msgstr != ""

    def _unit(self, key, entry):
        context = "\n".join(filter(None, [entry.msgctxt, entry.comment]))
        return TranslationUnit(key=key, source=entry.msgid, context=context)

    def apply(self, key, translation):
        entry = self._entries[key]
        entry.msgstr = translation

    def save(self):
        save_po(self.po)
