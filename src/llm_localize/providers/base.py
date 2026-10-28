"""Base classes for LLM provider clients."""
import abc
import json
import logging
import os
import random
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Rate limited, or the service is briefly unavailable or overloaded
TRANSIENT_STATUS_CODES = (429, 500, 502, 503, 504, 529)

# Bad credentials, billing, permissions, or a wrong URL or model: every
# request will fail the same way
FATAL_STATUS_CODES = (401, 402, 403, 404)

# Longest wait between retries, in seconds, unless the server asks for
# longer with Retry-After, which is honoured up to MAX_RETRY_AFTER
MAX_RETRY_DELAY = 60
MAX_RETRY_AFTER = 300


def urlopen(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


class LLMError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TransientError(LLMError):
    """Raised by providers for failures worth retrying, like rate limits and overload.

    :param retry_after: seconds the server asked the caller to wait, if it said
    """

    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message, status=status)
        self.retry_after = retry_after


class FatalError(LLMError):
    """Raised by providers for failures that every request will hit, like a bad API key.

    Stops the whole run instead of failing each batch in turn.
    """


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

    Waits as long as the error's ``retry_after`` says, when it says,
    otherwise ``backoff_delay(attempt, **backoff)``.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except TransientError as e:
            if attempt == max_retries:
                raise
            if e.retry_after is not None:
                delay = min(e.retry_after, MAX_RETRY_AFTER)
            else:
                delay = backoff_delay(attempt, **backoff)
            logger.info("%s; retrying in %.0fs", e, delay)
            sleep(delay)


def retry_after(headers):
    """Return the wait in seconds that ``Retry-After`` (or ``retry-after-ms``) asks for, or None.

    The HTTP-date form of ``Retry-After`` isn't supported and is ignored.

    >>> retry_after({"Retry-After": "7"}), retry_after({"retry-after-ms": "1500"}), retry_after({})
    (7.0, 1.5, None)
    """
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    for name, scale in (("retry-after-ms", 1000), ("retry-after", 1)):
        try:
            return max(0.0, float(headers[name]) / scale)
        except (KeyError, ValueError, TypeError):
            continue
    return None


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

    def post_json(self, url, payload, headers):
        """POST ``payload`` as JSON and return the decoded JSON response.

        Raises ``TransientError`` for rate limits, overload, timeouts and
        connection failures, ``FatalError`` for authentication, billing,
        permission and not-found errors, and ``LLMError`` for other HTTP
        errors. Each includes the API's error message.
        """
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            raise self.http_error(e) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise TransientError(f"Can't reach {url}: {e}") from e

    @staticmethod
    def http_error(error):
        try:
            detail = error.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        finally:
            # Its body may be a temporary file, kept open until closed
            error.close()
        message = f"HTTP {error.code} from {error.url}: {detail or error.reason}"
        if error.code in TRANSIENT_STATUS_CODES:
            return TransientError(message, status=error.code, retry_after=retry_after(error.headers))
        if error.code in FATAL_STATUS_CODES:
            return FatalError(message, status=error.code)
        return LLMError(message, status=error.code)
