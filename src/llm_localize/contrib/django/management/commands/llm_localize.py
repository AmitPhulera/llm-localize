from django.core.management.base import BaseCommand

from llm_localize import cli
from llm_localize.contrib.django.conf import get_config


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
