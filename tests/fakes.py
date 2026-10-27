"""Test doubles for LLM clients."""
import json

from llm_localize.providers.base import LLMClient


class FakeClient(LLMClient):
    """Translates by prefixing each message, which keeps placeholders intact.

    Plural forms get the singular or plural source depending on whether the
    form is described as only "used when n is 1".
    """

    default_model = "fake-model"
    api_key_env_var = "FAKE_API_KEY"

    def __init__(self, api_key="key", prefix="T: ", **kwargs):
        super().__init__(api_key, **kwargs)
        self.prefix = prefix
        self.calls = []

    def call_llm(self, system_prompt, user_message):
        self.calls.append((system_prompt, user_message, self.model))
        output = {}
        for key, value in json.loads(user_message).items():
            if isinstance(value, str):
                output[key] = self.prefix + value
            elif "forms" in value:
                for index, description in value["forms"].items():
                    source = value["singular"] if description == "used when n is 1" else value["plural"]
                    output[f"{key}:{index}"] = self.prefix + source
            else:
                output[key] = self.prefix + value["text"]
        return json.dumps(output)
