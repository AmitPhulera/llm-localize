"""Base classes for LLM provider clients."""
import logging
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
