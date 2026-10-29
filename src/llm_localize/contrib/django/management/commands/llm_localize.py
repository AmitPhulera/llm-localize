from django.core.management.base import BaseCommand, CommandError

from llm_localize import cli
from llm_localize.contrib.django.conf import get_config
from llm_localize.formats.po import find_po_files
from llm_localize.providers.base import LLMError


class Command(BaseCommand):
    help = (
        "Translate untranslated messages with an LLM, in the PO files in LOCALE_PATHS for every "
        "language in LANGUAGES."
    )

    def add_arguments(self, parser):
        config = get_config()
        parser.add_argument('--langs', nargs='+',
                            help="Languages to translate to (default: settings.LANGUAGES minus the "
                                 "source language)")
        parser.add_argument('--domains', nargs='+', default=config['DOMAINS'],
                            help="gettext domains to look for (default: %(default)s)")
        parser.add_argument('--locale-dirs', nargs='+', default=config['LOCALE_PATHS'],
                            help="Locale directories to look in (default: LOCALE_PATHS, or ./locale)")
        cli.add_translation_arguments(parser, config)

    def handle(self, *args, **options):
        # The logger is put back as it was afterwards: the command may run in a larger program, by call_command()
        with cli.logging_to(options['verbosity'], self.stdout, self.stderr):
            self._handle(options)

    def _handle(self, options):
        config = get_config()
        jobs = self._jobs(options, config)
        if not jobs:
            raise CommandError("No translation files found")
        try:
            results = cli.run(_Options(options), jobs, api_key=config['API_KEY'],
                              model_params=config['MODEL_PARAMS'])
        except (LLMError, ValueError, OSError) as e:
            raise CommandError(cli.error_message(e)) from e
        failed = sum(result.failed_batches for result in results)
        if failed:
            raise CommandError(f"{failed} batches failed; rerun to retry them")

    def _jobs(self, options, config):
        langs = options['langs']
        return list(find_po_files(options['locale_dirs'], langs or config['LANGUAGES'], options['domains']))


class _Options:
    """Exposes the command's options dict with the attribute names ``cli.run`` expects."""

    def __init__(self, options):
        self.__dict__.update(options)
