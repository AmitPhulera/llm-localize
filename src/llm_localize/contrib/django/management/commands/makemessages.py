"""Django's ``makemessages``, optionally followed by ``llm_localize`` on the files it just updated.

Opt in for one run with ``--translate``, or for the project with
``LLM_LOCALIZE = {"AFTER_MAKEMESSAGES": True}`` (then ``--no-translate``
skips it once).

Translates the same locales (``--locale``, minus ``--exclude``; otherwise
the configured languages), the same ``--domain`` and every locale
directory ``makemessages`` wrote to. The source language is skipped.
"""
import argparse

from django.core.management import call_command
from django.core.management.commands import makemessages

from llm_localize.contrib.django.conf import get_config
from llm_localize.languages import same_language, to_locale


class Command(makemessages.Command):
    help = makemessages.Command.help + " With --translate, then fills in missing translations with an LLM."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--translate', action=argparse.BooleanOptionalAction, default=None,
            help="Translate untranslated messages with an LLM afterwards "
                 "(default: LLM_LOCALIZE['AFTER_MAKEMESSAGES'], which is off)",
        )

    def handle(self, *args, **options):
        super().handle(*args, **options)
        config = get_config()
        translate = options['translate']
        if translate is None:
            translate = config['AFTER_MAKEMESSAGES']
        if not translate:
            return

        langs = options['locale'] or config['LANGUAGES']
        # --exclude takes locale names (pt_BR), LANGUAGES has codes (pt-br)
        excluded = {to_locale(lang) for lang in options['exclude']}
        langs = [
            lang for lang in langs
            if to_locale(lang) not in excluded and not same_language(lang, config['SOURCE_LANGUAGE'])
        ]
        # Without locale directories, as when makemessages found nothing to extract, there's nothing to translate
        if not langs or not self.locale_paths:
            return
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
