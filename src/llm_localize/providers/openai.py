"""OpenAI-compatible chat completions API.

Works with OpenAI and the many servers that copy its API, such as
OpenRouter, Groq, Together, Mistral, vLLM, LM Studio and Ollama: point
``api_base`` at the server's ``/v1`` URL.
"""
from llm_localize.providers.base import HttpClient, LLMError, merge_params

# Constrains output to a flat string map. strict=False because strict mode
# doesn't accept additionalProperties-only schemas. Servers without
# json_schema support can be given another format, or none, through
# model_params, e.g. {"response_format": {"type": "json_object"}} or
# {"response_format": None}.
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "translations",
        "strict": False,
        "schema": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


def default_model_params(model):
    return {"temperature": 0.2}


class OpenAIClient(HttpClient):
    default_model = "gpt-6-luna"
    default_api_base = "https://api.openai.com/v1"
    api_base_env_var = "OPENAI_BASE_URL"
    api_key_env_var = "OPENAI_API_KEY"

    def call_llm(self, system_prompt, user_message):
        overrides = {key: value for key, value in self.model_params.items() if key != "response_format"}
        payload = merge_params(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                **default_model_params(self.model),
            },
            overrides,
        )
        # Replaced, not merged, so a different format type doesn't inherit json_schema's fields
        response_format = self.model_params.get("response_format", RESPONSE_FORMAT)
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self.post_json(f"{self.api_base}/chat/completions", payload, headers)
        if not response.get("choices"):
            raise LLMError(f"Reply without choices from {self.api_base}: {str(response)[:200]}")
        choice = response["choices"][0]
        return choice["message"]["content"]
