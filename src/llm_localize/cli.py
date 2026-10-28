"""``llm-localize`` command line tool, usable without Django."""
from llm_localize.formats import FORMATS
from llm_localize.providers import PROVIDERS


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
    'EXTRA_INSTRUCTIONS': '',
}
