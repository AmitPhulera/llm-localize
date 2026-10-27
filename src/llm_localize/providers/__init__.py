"""Registry of LLM providers.

A provider is named either by a key in ``PROVIDERS`` or by the dotted
path to an ``LLMClient`` subclass, e.g. ``"myproject.llm.MyClient"``.
"""
from llm_localize.providers.base import LLMClient, LLMError
from llm_localize.utils import import_class

PROVIDERS = {}


def get_client_class(provider):
    try:
        return import_class(PROVIDERS.get(provider, provider), LLMClient)
    except ImportError as e:
        raise LLMError(f"Unknown LLM provider {provider!r}: {e}") from e
