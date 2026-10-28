"""Shared driver for the CLI and the Django management command."""
import logging

from llm_localize.engine import FileResult, translate_file
from llm_localize.formats import open_file

logger = logging.getLogger(__name__)

# How many distinct errors a summary lists before counting the rest
MAX_ERRORS_SHOWN = 5


def resolve_language(translation_file, language=None):
    language = language or translation_file.language
    if not language:
        raise ValueError(f"Can't tell the target language of {translation_file.path}; pass it explicitly")
    return language


def translate_files(jobs, client, source_language="en", batch_size=50, workers=10, extra_instructions="",
                    format=None, cleanup=True, cleanup_only=False):
    """Translate each ``(path, language)`` job and return a ``FileResult`` per file.

    ``language`` may be None to use the language the file declares. With
    ``cleanup_only``, no LLM calls are made: only the format's cleanup
    runs, and ``client`` may be None.

    ``cleanup_only`` can't be combined with ``cleanup=False``.

    If a file raises, the exception gets a ``results`` attribute with the
    results of the files finished before it, so callers can still report them.
    """
    if cleanup_only and not cleanup:
        raise ValueError("cleanup_only can't be used with cleanup=False")
    results = []
    for path, language in jobs:
        try:
            results.append(_translate_one(
                path, language, client, source_language, batch_size, workers, extra_instructions,
                format, cleanup, cleanup_only,
            ))
        except Exception as e:
            e.results = results
            raise
    return results


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


def summarize(result):
    """Describe a ``FileResult`` in a few lines, mentioning only what happened.

    >>> from collections import Counter
    >>> print(summarize(FileResult(
    ...     path="fr.po", language="fr", untranslated=10, translated=6, batches=3, failed_batches=2,
    ...     rejected=Counter({"placeholders": 2, "HTML tags": 1}), errors=Counter({"HTTP 503: busy": 2}),
    ... )))
    fr.po (fr): translated 6 of 10
      rejected 3: placeholders 2, HTML tags 1
      2 of 3 batches failed:
        HTTP 503: busy (2 batches)
    """
    name = f"{result.path} ({result.language})" if result.language else result.path
    if not result.batches:
        lines = [f"{name}: nothing to translate"]
    else:
        lines = [f"{name}: translated {result.translated} of {result.untranslated}"]
    if result.rejected:
        reasons = ", ".join(f"{reason} {count}" for reason, count in result.rejected.most_common())
        lines.append(f"  rejected {result.rejected.total()}: {reasons}")
    if result.failed_batches:
        lines.append(f"  {result.failed_batches} of {result.batches} batches failed:")
        # The commonest few, so a run whose batches each fail differently still gets a short summary
        errors = result.errors.most_common()
        lines.extend(
            f"    {error}" + (f" ({count} batches)" if count > 1 else "")
            for error, count in errors[:MAX_ERRORS_SHOWN]
        )
        if len(errors) > MAX_ERRORS_SHOWN:
            others = errors[MAX_ERRORS_SHOWN:]
            lines.append(f"    and {len(others)} other errors ({sum(count for _, count in others)} batches)")
    if result.cleared:
        lines.append(f"  cleared {result.cleared} broken translations")
    return "\n".join(lines)
