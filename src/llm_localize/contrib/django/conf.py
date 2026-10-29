"""Settings for the Django integration, read from ``settings.LLM_LOCALIZE``.

Every key is optional::

    LLM_LOCALIZE = {
        "PROVIDER": "openai",          # "openai", "anthropic", "gemini", "grok", or a dotted path
        "API_BASE": None,              # None: the provider's API; set for compatible servers
        "MODEL": None,                 # None: the provider's default
        "API_KEY": None,               # None: LLM_LOCALIZE_API_KEY, then e.g. OPENAI_API_KEY
        "MODEL_PARAMS": {},            # extra request params, e.g. {"temperature": 0}
        "SOURCE_LANGUAGE": None,       # None: settings.LANGUAGE_CODE
        "LANGUAGES": None,             # None: settings.LANGUAGES minus the source language
        "LOCALE_PATHS": None,          # None: settings.LOCALE_PATHS, or ./locale
        "DOMAINS": ["django", "djangojs"],
        "FORMAT": None,                # None: detect from the file extension
        "BATCH_SIZE": 50,
        "WORKERS": 10,
        "EXTRA_INSTRUCTIONS": "",      # e.g. "Use gender-neutral language."
    }
"""
from pathlib import Path

from django.conf import settings

from llm_localize.cli import DEFAULTS
from llm_localize.languages import same_language


def get_config():
    config = {
        **DEFAULTS,
        'SOURCE_LANGUAGE': None,
        'LANGUAGES': None,
        'LOCALE_PATHS': None,
        'DOMAINS': ['django', 'djangojs'],
        **getattr(settings, 'LLM_LOCALIZE', {}),
    }
    if not config['SOURCE_LANGUAGE']:
        config['SOURCE_LANGUAGE'] = settings.LANGUAGE_CODE
    if config['LANGUAGES'] is None:
        config['LANGUAGES'] = [
            code for code, _name in settings.LANGUAGES
            if not same_language(code, config['SOURCE_LANGUAGE'])
        ]
    if config['LOCALE_PATHS'] is None:
        config['LOCALE_PATHS'] = list(settings.LOCALE_PATHS) or [Path('locale')]
    return config
