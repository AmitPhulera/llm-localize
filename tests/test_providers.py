import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from llm_localize.providers import get_client, get_client_class
from llm_localize.providers.base import (
    HttpClient,
    LLMError,
    TransientError,
    retry_with_exponential_backoff,
)

from .fakes import FakeClient


def json_response(data):
    return io.BytesIO(json.dumps(data).encode())


def http_error(code, body=b'{"error": "nope"}'):
    return urllib.error.HTTPError("https://host/x", code, "reason", {}, io.BytesIO(body))


class FakeHttp:
    """Patches ``urlopen`` to return queued responses and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json_response(response)

    @property
    def payload(self):
        return json.loads(self.requests[-1].data)

    def header(self, name):
        return self.requests[-1].get_header(name.capitalize())


@pytest.fixture
def fake_http():
    def install(*responses):
        fake = FakeHttp(*responses)
        patcher = patch("llm_localize.providers.base.urlopen", fake)
        patcher.start()
        installed.append(patcher)
        return fake

    installed = []
    yield install
    for patcher in installed:
        patcher.stop()


@pytest.fixture(autouse=True)
def no_provider_env(monkeypatch):
    for name in ["FAKE_API_KEY"]:
        monkeypatch.delenv(name, raising=False)


class TestRegistry:

    @pytest.mark.parametrize("provider, client_class", [
        ("tests.fakes.FakeClient", FakeClient),
    ])
    def test_lookup(self, provider, client_class):
        assert get_client_class(provider) is client_class

    @pytest.mark.parametrize("provider", ["nope", "tests.fakes.Missing"])
    def test_unknown(self, provider):
        with pytest.raises(LLMError):
            get_client_class(provider)

    @pytest.mark.parametrize("provider", ["tests.fakes.FakeClient"])
    def test_generic_api_key_env_var(self, monkeypatch, provider):
        monkeypatch.setenv("LLM_LOCALIZE_API_KEY", "generic")

        assert get_client(provider).api_key == "generic"

    def test_client_gets_api_key_when_created(self, monkeypatch):
        monkeypatch.setenv("FAKE_API_KEY", "secret")
        seen = []

        class AuthClient(FakeClient):
            def __init__(self, api_key=None, **kwargs):
                seen.append(api_key)
                super().__init__(api_key, **kwargs)

        with patch("llm_localize.providers.get_client_class", return_value=AuthClient):
            get_client("auth")

        assert seen == ["secret"]

    @pytest.mark.parametrize("provider, env_var", [
        ("tests.fakes.FakeClient", "FAKE_API_KEY"),
    ])
    def test_api_key_required_for_default_host(self, provider, env_var):
        with pytest.raises(LLMError, match=f"LLM_LOCALIZE_API_KEY or {env_var}"):
            get_client(provider)


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


class TestPostJson:

    def client(self):
        return NoDefaultHost(api_key="k", api_base="https://host")

    def test_error_responses_are_closed(self, fake_http):
        error = http_error(400)
        fake_http(error)

        with pytest.raises(LLMError):
            self.client().post_json("https://host/x", {}, {})
        assert error.fp is None or error.fp.closed

    def test_other_status_includes_api_message(self, fake_http):
        fake_http(http_error(400, b'{"error": "prompt is too long"}'))

        with pytest.raises(LLMError, match="prompt is too long") as error:
            self.client().post_json("https://host/x", {}, {})
        assert not isinstance(error.value, TransientError)
        assert error.value.status == 400

    def test_connection_failure_is_transient(self, fake_http):
        fake_http(urllib.error.URLError("connection refused"))

        with pytest.raises(TransientError, match="connection refused"):
            self.client().post_json("https://host/x", {}, {})


class NoDefaultHost(HttpClient):
    default_model = "m"
    api_key_env_var = "FAKE_API_KEY"

    def call_llm(self, system_prompt, user_message):
        return "{}"


def test_client_without_default_host_needs_api_base():
    with (patch("llm_localize.providers.get_client_class", return_value=NoDefaultHost),
          pytest.raises(LLMError, match="no default_api_base")):
        get_client("custom")


def test_client_without_default_model():
    class NoDefault(HttpClient):
        default_api_base = "https://example.com"

        def call_llm(self, system_prompt, user_message):
            return "{}"

    with pytest.raises(LLMError, match="no default model"):
        NoDefault(api_key="k")
