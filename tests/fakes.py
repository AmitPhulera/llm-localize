"""Test doubles for LLM clients and translation files."""
import json
import threading

from llm_localize.formats.base import TranslationFile
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


class ScriptedClient(LLMClient):
    """Replies with each item of ``replies`` in turn.

    An exception is raised, a dict is sent back as JSON, and anything else
    is sent back as is.
    """

    default_model = "fake-model"

    def __init__(self, replies, **kwargs):
        super().__init__("key", max_retries=0, **kwargs)
        self.replies = list(replies)
        self.calls = []
        self.lock = threading.Lock()

    def call_llm(self, system_prompt, user_message):
        with self.lock:
            self.calls.append(user_message)
            reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply) if isinstance(reply, dict) else reply


class DictFile(TranslationFile):
    """An in-memory format: ``{key: (source, translation)}``."""

    name = "dict"
    extensions = (".dict",)
    instructions = "Dict rules."

    def __init__(self, path="memory.dict", messages=None, language="es"):
        super().__init__(path)
        self.messages = dict(messages or {})
        self._language = language
        self.saves = 0
        self.cleanups = 0

    @property
    def language(self):
        return self._language

    def untranslated_units(self):
        from llm_localize.units import TranslationUnit
        return [TranslationUnit(key=key, source=source)
                for key, (source, translation) in self.messages.items() if not translation]

    def apply(self, key, translation):
        source, _ = self.messages[key]
        self.messages[key] = (source, translation)

    def save(self):
        self.saves += 1

    def cleanup(self):
        self.cleanups += 1
        return 0
