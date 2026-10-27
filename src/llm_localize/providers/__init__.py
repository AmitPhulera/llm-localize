"""Registry of LLM providers.

A provider is named either by a key in ``PROVIDERS`` or by the dotted
path to an ``LLMClient`` subclass, e.g. ``"myproject.llm.MyClient"``.
"""
import os

from llm_localize.providers.base import LLMClient, LLMError
from llm_localize.utils import import_class

# Read for every provider, before the provider's own variable
API_KEY_ENV_VAR = 'LLM_LOCALIZE_API_KEY'

PROVIDERS = {}


def get_client_class(provider):
    try:
        return import_class(PROVIDERS.get(provider, provider), LLMClient)
    except ImportError as e:
        raise LLMError(f"Unknown LLM provider {provider!r}: {e}") from e


def get_client(provider='openai', api_key=None, **kwargs):
    """Build a client, reading the API key from the environment if not given.

    The key comes from ``LLM_LOCALIZE_API_KEY``, then the provider's own
    variable, its ``api_key_env_var``. Keyword arguments go to the client,
    e.g. ``model`` or ``api_base``.
    """
    client_class = get_client_class(provider)
    env_vars = [API_KEY_ENV_VAR]
    if client_class.api_key_env_var:
        env_vars.append(client_class.api_key_env_var)
    api_key = api_key or next(filter(None, map(os.environ.get, env_vars)), None)
    client = client_class(api_key=api_key, **kwargs)
    if client.requires_api_key and not client.api_key:
        raise LLMError(
            f"No API key for provider {provider!r}. Pass one explicitly "
            f"or set the {' or '.join(env_vars)} environment variable.")
    return client
