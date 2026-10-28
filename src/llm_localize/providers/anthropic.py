"""Anthropic Messages API.

Works with the Claude API and servers that copy its API: point
``api_base`` at the server's root URL (without ``/v1``).
"""
import logging

from llm_localize.providers.base import HttpClient, LLMError, merge_params, output_limit_error

logger = logging.getLogger(__name__)

API_VERSION = "2026-10-21"

# Re-runs a request that Claude's safety classifiers decline on the model
# Anthropic recommends for that category. Only sent to the Claude API
# itself, since compatible servers may not accept it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


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
    # Set once the API refuses FALLBACK_BETA, as it will when Anthropic retires it
    fallback_beta_refused = False

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
        if self.uses_default_host and not self.fallback_beta_refused:
            payload["fallbacks"] = "default"
            headers["anthropic-beta"] = FALLBACK_BETA
        try:
            response = self.post_json(
                f"{self.api_base}/v1/messages", merge_params(payload, self.model_params), headers)
        except LLMError as e:
            # Without the beta a request still works, only without fallbacks
            if "anthropic-beta" not in headers or e.status != 400 or FALLBACK_BETA not in str(e):
                raise
            logger.warning("Anthropic's API refused the %s beta; sending requests without it", FALLBACK_BETA)
            self.fallback_beta_refused = True
            return self.call_llm(system_prompt, user_message)
        if response.get("stop_reason") == "max_tokens":
            raise output_limit_error(self.model)
        if response.get("stop_reason") == "refusal":
            category = (response.get("stop_details") or {}).get("category")
            raise LLMError(f"{self.model} declined the request (category: {category})")
        return "".join(
            block.get("text", "") for block in response.get("content", []) if block.get("type") == "text"
        )
