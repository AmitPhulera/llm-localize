"""Django's ``makemessages``, optionally followed by ``llm_localize`` on the files it just updated.

Opt in with ``--translate``.

Translates the same locales (``--locale``, otherwise the configured
languages), the same ``--domain`` and every locale directory
``makemessages`` wrote to.
"""
import argparse

from django.core.management import call_command
from django.core.management.commands import makemessages

from llm_localize.contrib.django.conf import get_config


class Command(makemessages.Command):
    help = makemessages.Command.help + " With --translate, then fills in missing translations with an LLM."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--translate', action=argparse.BooleanOptionalAction, default=None,
            help="Translate untranslated messages with an LLM afterwards",
        )

    def handle(self, *args, **options):
        super().handle(*args, **options)
        config = get_config()
        translate = options['translate']
        if not translate:
            return

        langs = options['locale'] or config['LANGUAGES']
        # The catalogs are already written, so a failure here leaves them
        # updated but partly untranslated; rerunning picks up the rest
        call_command(
            'llm_localize',
            '--langs', *langs,
            '--domains', options['domain'],
            '--locale-dirs', *self.locale_paths,
            verbosity=options['verbosity'],
            stdout=self.stdout,
            stderr=self.stderr,
        )
