"""OpenAI-compatible chat completions API.

Works with OpenAI and the many servers that copy its API, such as
OpenRouter, Groq, Together, Mistral, vLLM, LM Studio and Ollama: point
``api_base`` at the server's ``/v1`` URL.
"""
from llm_localize.providers.base import HttpClient, LLMError, merge_params


def default_model_params(model):
    return {"temperature": 0.2}


class OpenAIClient(HttpClient):
    default_model = "gpt-6-luna"
    default_api_base = "https://api.openai.com/v1"
    api_base_env_var = "OPENAI_BASE_URL"
    api_key_env_var = "OPENAI_API_KEY"

    def call_llm(self, system_prompt, user_message):
        payload = merge_params(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                **default_model_params(self.model),
            },
            self.model_params,
        )
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self.post_json(f"{self.api_base}/chat/completions", payload, headers)
        if not response.get("choices"):
            raise LLMError(f"Reply without choices from {self.api_base}: {str(response)[:200]}")
        choice = response["choices"][0]
        return choice["message"]["content"]
