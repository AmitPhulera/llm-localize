"""Base classes for LLM provider clients."""
import random

# Longest wait between retries, in seconds
MAX_RETRY_DELAY = 60


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
