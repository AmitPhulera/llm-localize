import http.server
import io
import json
import threading
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from llm_localize.providers import get_client, get_client_class
from llm_localize.providers.base import (
    FatalError,
    HttpClient,
    LLMError,
    TransientError,
    retry_with_exponential_backoff,
)
from llm_localize.providers.openai import OpenAIClient

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
    for name in ["OPENAI_API_KEY", "OPENAI_BASE_URL", "FAKE_API_KEY"]:
        monkeypatch.delenv(name, raising=False)


class TestRegistry:

    @pytest.mark.parametrize("provider, client_class", [
        ("openai", OpenAIClient),
        ("tests.fakes.FakeClient", FakeClient),
    ])
    def test_lookup(self, provider, client_class):
        assert get_client_class(provider) is client_class

    @pytest.mark.parametrize("provider", ["nope", "tests.fakes.Missing"])
    def test_unknown(self, provider):
        with pytest.raises(LLMError):
            get_client_class(provider)

    @pytest.mark.parametrize("provider", ["openai", "tests.fakes.FakeClient"])
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
        ("openai", "OPENAI_API_KEY"),
    ])
    def test_api_key_required_for_default_host(self, provider, env_var):
        with pytest.raises(LLMError, match=f"LLM_LOCALIZE_API_KEY or {env_var}"):
            get_client(provider)

    def test_defaults_and_overrides(self):
        client = get_client("openai", api_key="k", model_params={"temperature": 0})

        assert (client.model, client.model_params) == ("gpt-6-luna", {"temperature": 0})


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

    @pytest.mark.parametrize("retry_after, expected", [(7, 7), (1000, 300)])
    def test_honours_retry_after_up_to_a_limit(self, retry_after, expected):
        sleep = MagicMock()
        outcomes = [TransientError("rate limited", retry_after=retry_after), "ok"]

        def func():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        retry_with_exponential_backoff(func, sleep=sleep)
        sleep.assert_called_once_with(expected)

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
        return OpenAIClient(api_key="k")

    @pytest.mark.parametrize("code", [429, 500, 503, 529])
    def test_transient_status(self, fake_http, code):
        fake_http(http_error(code))

        with pytest.raises(TransientError) as error:
            self.client().post_json("https://host/x", {}, {})
        assert error.value.status == code

    def test_retry_after_header(self, fake_http):
        headers = {"Retry-After": "12"}
        fake_http(urllib.error.HTTPError("https://host/x", 429, "Too Many", headers, io.BytesIO(b"")))

        with pytest.raises(TransientError) as error:
            self.client().post_json("https://host/x", {}, {})
        assert error.value.retry_after == 12

    @pytest.mark.parametrize("code", [401, 402, 403, 404])
    def test_fatal_status(self, fake_http, code):
        fake_http(http_error(code, b'{"error": "invalid key"}'))

        with pytest.raises(FatalError, match="invalid key") as error:
            self.client().post_json("https://host/x", {}, {})
        assert error.value.status == code

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
        assert not isinstance(error.value, (TransientError, FatalError))
        assert error.value.status == 400

    def test_connection_failure_is_transient(self, fake_http):
        fake_http(urllib.error.URLError("connection refused"))

        with pytest.raises(TransientError, match="connection refused"):
            self.client().post_json("https://host/x", {}, {})


def openai_reply(content):
    return {"choices": [{"message": {"content": content}}]}


class TestOpenAI:

    def test_request(self, fake_http):
        http = fake_http(openai_reply('{"0": "Hola"}'))

        assert OpenAIClient(api_key="k", model="gpt-4o").complete("system", "user") == '{"0": "Hola"}'

        assert http.requests[0].full_url == "https://api.openai.com/v1/chat/completions"
        assert http.header("Authorization") == "Bearer k"
        assert http.payload["messages"] == [
            {"role": "system", "content": "system"}, {"role": "user", "content": "user"},
        ]
        assert http.payload["temperature"] == 0.2
        assert http.payload["response_format"]["type"] == "json_schema"
        assert "reasoning_effort" not in http.payload

    def test_reasoning_models_turn_reasoning_off(self, fake_http):
        http = fake_http(openai_reply("{}"))

        OpenAIClient(api_key="k", model="gpt-6-luna").call_llm("system", "user")

        assert http.payload["reasoning_effort"] == "none"

    def test_model_params_override_defaults(self, fake_http):
        http = fake_http(openai_reply("{}"))

        OpenAIClient(api_key="k", model_params={"temperature": 0, "seed": 1}).complete("system", "user")

        assert (http.payload["temperature"], http.payload["seed"]) == (0, 1)

    def test_bad_request_is_not_retried(self, fake_http):
        http = fake_http(http_error(400, b'{"error": "context length exceeded"}'))

        with pytest.raises(LLMError, match="context length exceeded"):
            OpenAIClient(api_key="k").complete("system", "user")
        assert len(http.requests) == 1

    def test_response_format_can_be_replaced(self, fake_http):
        http = fake_http(openai_reply("{}"))

        OpenAIClient(api_key="k", model_params={"response_format": {"type": "json_object"}}).complete("s", "u")

        assert http.payload["response_format"] == {"type": "json_object"}

    def test_response_format_can_be_dropped(self, fake_http):
        http = fake_http(openai_reply("{}"))

        OpenAIClient(api_key="k", model_params={"response_format": None}).complete("s", "u")

        assert "response_format" not in http.payload

    def test_output_limit(self, fake_http):
        fake_http({"choices": [{"message": {"content": '{"0": "Ho'}, "finish_reason": "length"}]})

        with pytest.raises(LLMError, match="output token limit"):
            OpenAIClient(api_key="k").complete("system", "user")

    def test_no_auth_header_without_key(self, fake_http):
        http = fake_http(openai_reply("{}"))

        OpenAIClient(api_base="http://localhost:11434/v1", model="llama").complete("system", "user")

        assert http.requests[0].full_url == "http://localhost:11434/v1/chat/completions"
        assert http.header("Authorization") is None

    def test_reply_without_choices(self, fake_http):
        fake_http({"error": "model not loaded"})

        with pytest.raises(LLMError, match="without choices.*model not loaded"):
            OpenAIClient(api_key="k").complete("system", "user")


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


def test_redirects_are_not_followed():
    """A redirect fails the request, so the API key never reaches another host."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        do_GET = do_POST

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAIClient(api_key="secret", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                              max_retries=0)
        with pytest.raises(LLMError, match="HTTP 302"):
            client.complete("system", "user")
    finally:
        server.shutdown()
        server.server_close()

    assert seen == [("/v1/chat/completions", "Bearer secret")]
