from unittest.mock import MagicMock, patch

import pytest

from llm_localize.providers.base import (
    LLMClient,
    LLMError,
    TransientError,
    retry_with_exponential_backoff,
)


class TestRetry:

    def test_retries_until_success(self):
        outcomes = [TransientError("rate limited"), TransientError("overloaded"), "ok"]
        sleep = MagicMock()

        def func():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        assert retry_with_exponential_backoff(func, jitter=False, sleep=sleep) == "ok"
        assert [call.args[0] for call in sleep.call_args_list] == [2, 4]

    def test_backs_off_then_gives_up(self):
        sleep = MagicMock()

        def func():
            raise TransientError("overloaded")

        with pytest.raises(TransientError):
            retry_with_exponential_backoff(func, max_retries=3, jitter=False, sleep=sleep)
        assert [call.args[0] for call in sleep.call_args_list] == [2, 4, 8]

    def test_waits_are_capped(self):
        sleep = MagicMock()

        def func():
            raise TransientError("overloaded")

        with patch("random.random", return_value=0.999), pytest.raises(TransientError):
            retry_with_exponential_backoff(func, max_retries=8, sleep=sleep)
        delays = [call.args[0] for call in sleep.call_args_list]
        assert max(delays) <= 60
        assert sum(delays[:5]) < 65

    def test_other_errors_propagate(self):
        calls = []

        def func():
            calls.append(1)
            raise LLMError("bad request", status=400)

        with pytest.raises(LLMError):
            retry_with_exponential_backoff(func)
        assert calls == [1]


def test_client_without_default_model():
    class NoDefault(LLMClient):
        def call_llm(self, system_prompt, user_message):
            return "{}"

    with pytest.raises(LLMError, match="no default model"):
        NoDefault(api_key="k")
