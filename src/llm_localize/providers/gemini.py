"""Google Gemini ``generateContent`` API.

Works with the Gemini API and servers that copy its API: point
``api_base`` at the server's root URL (without ``/v1beta``).
"""
from llm_localize.providers.base import HttpClient, LLMError, merge_params


class GeminiClient(HttpClient):
    """Gemini ``generateContent`` client.

    ``temperature`` is left at the model's default, which Google
    recommends for Gemini 3 models. Use ``model_params`` for other request
    fields, e.g. ``{"generationConfig": {"temperature": 0.2}}``.
    """

    default_model = "gemini-3.8-flash"
    default_api_base = "https://generativelanguage.googleapis.com"
    api_base_env_var = "GEMINI_BASE_URL"
    api_key_env_var = "GEMINI_API_KEY"
    api_version = "v1beta"

    def call_llm(self, system_prompt, user_message):
        payload = merge_params(
            {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            self.model_params,
        )
        headers = {"x-goog-api-key": self.api_key} if self.api_key else {}
        url = f"{self.api_base}/{self.api_version}/models/{self.model}:generateContent"
        response = self.post_json(url, payload, headers)
        candidates = response.get("candidates") or []
        if not candidates:
            reason = (response.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise LLMError(f"{self.model} returned no translation: {reason}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        return text
