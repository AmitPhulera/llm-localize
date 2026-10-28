"""Shared driver for the CLI and the Django management command."""
import logging

from llm_localize.engine import FileResult, translate_file
from llm_localize.formats import open_file

logger = logging.getLogger(__name__)


def resolve_language(translation_file, language=None):
    language = language or translation_file.language
    if not language:
        raise ValueError(f"Can't tell the target language of {translation_file.path}; pass it explicitly")
    return language


def _translate_one(path, language, client, source_language, batch_size, workers, extra_instructions,
                   format, cleanup, cleanup_only):
    translation_file = open_file(path, format=format, language=language, source_language=source_language)
    if cleanup_only:
        # Cleanup doesn't need the target language, so a file needn't declare one
        language = language or translation_file.language or ""
        return FileResult(path=str(path), language=language, cleared=translation_file.cleanup())
    language = resolve_language(translation_file, language)
    logger.info("Translating %s to %s", path, language)
    return translate_file(
        translation_file, client, language,
        source_language=source_language,
        batch_size=batch_size,
        workers=workers,
        extra_instructions=extra_instructions,
        cleanup=cleanup,
    )
