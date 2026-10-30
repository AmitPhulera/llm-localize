"""Django integration: add ``"llm_localize.contrib.django"`` to ``INSTALLED_APPS``."""


def get_translator(**overrides):
    """Return a ``StringTranslator`` built from ``settings.LLM_LOCALIZE``, with keyword overrides."""
    from llm_localize import StringTranslator
    from llm_localize.contrib.django.conf import get_config

    return StringTranslator.from_config(get_config(), **overrides)


def get_file_translator(**overrides):
    """Return a ``FileTranslator`` built from ``settings.LLM_LOCALIZE``, with keyword overrides."""
    from llm_localize import FileTranslator
    from llm_localize.contrib.django.conf import get_config

    return FileTranslator.from_config(get_config(), **overrides)
