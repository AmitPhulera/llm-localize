"""Base classes for LLM provider clients."""
import abc
import logging
import os
import random
import time

logger = logging.getLogger(__name__)

# Longest wait between retries, in seconds
MAX_RETRY_DELAY = 60


class LLMError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TransientError(LLMError):
    """Raised by providers for failures worth retrying, like rate limits and overload."""


def backoff_delay(attempt, initial_delay=2, exponential_base=2, max_delay=MAX_RETRY_DELAY, jitter=True):
    """Return how long to wait before retry number ``attempt`` (from 0).

    The delay doubles up to ``max_delay``. Jitter scales it down by up to
    half, so parallel batches don't all retry at once.

    >>> [backoff_delay(attempt, jitter=False) for attempt in range(7)]
    [2, 4, 8, 16, 32, 60, 60]
    """
    delay = min(max_delay, initial_delay * exponential_base ** attempt)
    if jitter:
        delay *= 0.5 + random.random() / 2
    return delay


def retry_with_exponential_backoff(func, *, max_retries=5, sleep=time.sleep, **backoff):
    """Call ``func()``, retrying with exponential backoff on ``TransientError``.

    Waits ``backoff_delay(attempt, **backoff)`` between attempts.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except TransientError as e:
            if attempt == max_retries:
                raise
            delay = backoff_delay(attempt, **backoff)
            logger.info("%s; retrying in %.0fs", e, delay)
            sleep(delay)


class LLMClient(abc.ABC):
    """Sends a system prompt and a user message to an LLM and returns its JSON text reply.

    Subclasses implement ``call_llm`` and raise ``TransientError`` for
    failures worth retrying, so ``complete`` can back off and retry.
    """

    default_model = None
    api_key_env_var = None

    def __init__(self, api_key=None, model=None, model_params=None, max_retries=5):
        self.api_key = api_key
        self.model = model or self.default_model
        self.model_params = model_params or {}
        self.max_retries = max_retries
        if not self.model:
            raise LLMError(f"{type(self).__name__} has no default model; pass one explicitly")

    @property
    def requires_api_key(self):
        return True

    def complete(self, system_prompt, user_message):
        return retry_with_exponential_backoff(
            lambda: self.call_llm(system_prompt, user_message),
            max_retries=self.max_retries,
        )

    @abc.abstractmethod
    def call_llm(self, system_prompt, user_message):
        """Return the model's raw text response, which should contain a JSON object."""


class HttpClient(LLMClient):
    """An ``LLMClient`` that talks to an HTTP JSON API using only the standard library.

    The API base URL is, in order: the ``api_base`` argument, the
    ``api_base_env_var`` environment variable, then ``default_api_base``.
    """

    default_api_base = None
    api_base_env_var = None

    def __init__(self, *args, api_base=None, timeout=600, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_base = self.resolve_api_base(api_base)
        self.timeout = timeout

    @classmethod
    def resolve_api_base(cls, api_base=None):
        """Return the API base URL a client built with ``api_base`` would use."""
        env_api_base = os.environ.get(cls.api_base_env_var) if cls.api_base_env_var else None
        resolved = api_base or env_api_base or cls.default_api_base
        if not resolved:
            raise LLMError(f"{cls.__name__} has no default_api_base; pass api_base")
        return resolved.rstrip("/")
