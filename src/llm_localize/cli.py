"""``llm-localize`` command line tool, usable without Django."""
import argparse
import logging
import sys

from llm_localize.formats import FORMATS
from llm_localize.providers import PROVIDERS, get_client
from llm_localize.providers.base import FatalError, LLMError
from llm_localize.runner import summarize, translate_files

VERBOSITY_LEVELS = {0: logging.WARNING, 1: logging.INFO}


def configure_logging(verbosity, progress_stream, error_stream):
    """Log progress to ``progress_stream`` and warnings and errors to ``error_stream``.

    Verbosity 0 logs only warnings and errors, 1 adds progress, and 2
    adds each rejected translation and tracebacks for failed batches.
    """
    progress = logging.StreamHandler(progress_stream)
    progress.addFilter(lambda record: record.levelno < logging.WARNING)
    errors = logging.StreamHandler(error_stream)
    errors.setLevel(logging.WARNING)
    logger = logging.getLogger('llm_localize')
    for handler in (progress, errors):
        handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [progress, errors]
    logger.setLevel(VERBOSITY_LEVELS.get(verbosity, logging.DEBUG))
    logger.propagate = False


def error_message(error):
    if isinstance(error, FatalError):
        return f"{error}\nStopped. Batches that finished before this were saved."
    return str(error)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {number}")
    return number


def add_translation_arguments(parser, defaults):
    """Add the options shared by the CLI and the Django command."""
    parser.add_argument('--source-lang', default=defaults['SOURCE_LANGUAGE'],
                        help="Language the source text is written in (default: %(default)s)")
    parser.add_argument('--format', default=defaults['FORMAT'],
                        help=f"File format, one of {', '.join(FORMATS)} or a dotted path to a "
                             "TranslationFile subclass (default: detect from the file extension)")
    parser.add_argument('--provider', default=defaults['PROVIDER'],
                        help=f"API style of the LLM, one of {', '.join(PROVIDERS)}, or a dotted path to an "
                             "LLMClient subclass (default: %(default)s)")
    parser.add_argument('--model', default=defaults['MODEL'],
                        help="Model to use (default: the provider's default)")
    parser.add_argument('--api-key', default=None,
                        help="API key (default: the LLM_LOCALIZE_API_KEY environment variable, then the "
                             "provider's own, e.g. OPENAI_API_KEY)")
    parser.add_argument('--batch-size', type=positive_int, default=defaults['BATCH_SIZE'],
                        help="Messages per LLM request (default: %(default)s)")
    parser.add_argument('--workers', type=positive_int, default=defaults['WORKERS'],
                        help="LLM requests in flight at once (default: %(default)s)")
    parser.add_argument('--instructions', default=defaults['EXTRA_INSTRUCTIONS'],
                        help="Extra instructions for the translator, e.g. tone or terminology")
    cleanup = parser.add_mutually_exclusive_group()
    cleanup.add_argument('--cleanup-only', action='store_true',
                         help="Only clear broken translations; don't translate anything")
    cleanup.add_argument('--no-cleanup', action='store_true',
                         help="Don't clear broken translations after translating")


DEFAULTS = {
    'SOURCE_LANGUAGE': 'en',
    'FORMAT': None,
    'PROVIDER': 'openai',
    'MODEL': None,
    'BATCH_SIZE': 50,
    'WORKERS': 10,
    'EXTRA_INSTRUCTIONS': '',
}


def run(options, jobs, api_key=None, model_params=None):
    """Build the client from parsed options and translate the jobs."""
    client = None
    if not options.cleanup_only:
        client = get_client(
            options.provider,
            api_key=options.api_key or api_key,
            model=options.model,
            model_params=model_params,
        )
    return translate_files(
        jobs, client,
        source_language=options.source_lang,
        batch_size=options.batch_size,
        workers=options.workers,
        extra_instructions=options.instructions,
        format=options.format,
        cleanup=not options.no_cleanup,
        cleanup_only=options.cleanup_only,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='llm-localize',
        description="Translate untranslated messages in translation files with an LLM.",
    )
    parser.add_argument('paths', nargs='+', help="Translation files to translate")
    parser.add_argument('--lang', help="Target language (default: the language each file declares)")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument('-q', '--quiet', action='store_const', const=0, dest='verbosity', default=1,
                           help="Only show the summary, warnings and errors")
    verbosity.add_argument('-v', '--verbose', action='store_const', const=2, dest='verbosity',
                           help="Also show each rejected translation and tracebacks")
    add_translation_arguments(parser, DEFAULTS)
    options = parser.parse_args(argv)
    # Progress goes to stderr too, keeping stdout for the summary
    configure_logging(options.verbosity, sys.stderr, sys.stderr)
    try:
        results = run(options, [(path, options.lang) for path in options.paths])
    except (LLMError, ValueError, OSError) as e:
        for result in getattr(e, "results", []):
            print(summarize(result))
        parser.exit(2, f"llm-localize: error: {error_message(e)}\n")
    for result in results:
        print(summarize(result))
    return 1 if any(result.failed_batches for result in results) else 0


if __name__ == '__main__':
    sys.exit(main())
