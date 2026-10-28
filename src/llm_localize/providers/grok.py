"""xAI's Grok models, through xAI's OpenAI-compatible chat completions API.

Grok accepts the same requests as OpenAI, including the json_schema
response format and temperature.
"""
from llm_localize.providers.openai import OpenAIClient


class GrokClient(OpenAIClient):
    default_model = "grok-4.7"
    default_api_base = "https://api.x.ai/v1"
    api_base_env_var = "XAI_BASE_URL"
    api_key_env_var = "XAI_API_KEY"
