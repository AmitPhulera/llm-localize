"""Translate a file's content at runtime, e.g. a file a user uploads."""
from collections import Counter
from dataclasses import dataclass, field

from llm_localize.strings import BaseTranslator


@dataclass
class FileTranslation:
    """A translated file.

    :ivar content: the translated file's bytes. Messages that couldn't be
        translated are left as they were: untranslated in a PO or XLIFF
        file, missing from a JSON or Android file, in the source language
        in a document.
    :ivar untranslated: how many messages needed translating
    :ivar translated: how many were translated
    :ivar cleared: how many translations the format's cleanup blanked
        afterwards, like PO entries msgfmt rejects
    :ivar rejected: ``Counter`` of reasons translations were rejected
    :ivar errors: ``Counter`` of error messages from failed batches
    """

    content: bytes
    untranslated: int = 0
    translated: int = 0
    cleared: int = 0
    rejected: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)

    @property
    def complete(self):
        return self.translated - self.cleared == self.untranslated


class FileTranslator(BaseTranslator):
    """Translates files' content with an LLM.

    Safe to share between threads. Takes the options of
    ``BaseTranslator``, and:

    :param max_bytes: the largest file accepted
    :param max_messages: the most messages a file may need translated,
        which bounds what one file can cost
    :param max_unpacked_bytes: for .docx and other ZIP-based files, the
        most their contents may unpack to
    """

    def __init__(self, *args, max_bytes=5_000_000, max_messages=2000, max_unpacked_bytes=50_000_000, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_bytes = max_bytes
        self.max_messages = max_messages
        self.max_unpacked_bytes = max_unpacked_bytes
