"""Translate a file's content at runtime, e.g. a file a user uploads.

``FileTranslator`` takes a file's bytes and name and returns the
translated file's bytes, using the same formats, checks and report as
the command line tool. For a file that holds its source and translation
together (PO, XLIFF, .xcstrings), the upload is filled in.

Uploads are untrusted: the content only ever goes in a temporary
directory under a fixed name, and only the extension of the given name
is used.
"""
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from llm_localize.engine import translate_file
from llm_localize.formats import format_class_for_path, get_format_class
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

    ::

        translator = FileTranslator(provider="anthropic", api_key="...")

        result = translator.translate(upload.read(), upload.name, "fr")
        result.content  # the translated file, e.g. to save or send back

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

    def translate(self, content, filename, language, format=None, source_language=None, instructions=None):
        """Return a ``FileTranslation`` of ``content`` into ``language``.

        :param content: the file's bytes, or text, which is encoded as UTF-8
        :param filename: the file's name; only its extension is used, to
            pick the format unless ``format`` is given
        :param format: a format name like ``"json"`` or ``"po"``, or a
            dotted path to a ``TranslationFile`` subclass
        :raises ValueError: for a file that isn't valid in its format
        :raises FatalError: for errors every request would hit, like a bad API key
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        suffix = Path(Path(filename).name).suffix.lower()
        format_class = get_format_class(format) if format else format_class_for_path(f"upload{suffix}")
        source_language = source_language or self.source_language
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(content)
            output = source
            translation_file = format_class.open(source, language=language, source_language=source_language)
            result = translate_file(
                translation_file, self.client, language,
                source_language=source_language,
                batch_size=self.batch_size,
                workers=self.workers,
                extra_instructions=self.instructions if instructions is None else instructions,
            )
            return FileTranslation(
                content=output.read_bytes(),
                untranslated=result.untranslated,
                translated=result.translated,
                cleared=result.cleared,
                rejected=result.rejected,
                errors=result.errors,
            )
