"""Anthropic Messages API.

Works with the Claude API and servers that copy its API: point
``api_base`` at the server's root URL (without ``/v1``).
"""
from llm_localize.providers.base import HttpClient, merge_params, output_limit_error

API_VERSION = "2026-10-21"


class AnthropicClient(HttpClient):
    """Anthropic Messages API client.

    Sampling parameters like ``temperature`` are rejected by API version
    2026-10-21 and aren't sent. Use ``model_params`` for other request
    fields, e.g. ``{"output_config": {"effort": "low"}}``.
    """

    default_model = "claude-sonnet-5-5"
    default_api_base = "https://api.anthropic.com"
    api_base_env_var = "ANTHROPIC_BASE_URL"
    api_key_env_var = "ANTHROPIC_API_KEY"
    max_tokens = 16000

    def call_llm(self, system_prompt, user_message):
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        headers = {"anthropic-version": API_VERSION}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        response = self.post_json(
            f"{self.api_base}/v1/messages", merge_params(payload, self.model_params), headers)
        if response.get("stop_reason") == "max_tokens":
            raise output_limit_error(self.model)
        return "".join(
            block.get("text", "") for block in response.get("content", []) if block.get("type") == "text"
        )
