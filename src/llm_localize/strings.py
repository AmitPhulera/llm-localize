"""Translate a list of strings at runtime, e.g. user content in a web app.

``StringTranslator`` runs the same engine as file translation: strings are
batched, sent in parallel, and each translation is checked for broken
placeholders, HTML tags and URLs. Translations that fail come back as
``None``.

LLM calls take seconds, so call it from a background task rather than
while handling a request.
"""
from collections import Counter
from dataclasses import dataclass, field

from llm_localize.cli import DEFAULTS
from llm_localize.engine import translate_file
from llm_localize.formats.base import TranslationFile
from llm_localize.providers import get_client
from llm_localize.units import TranslationUnit


class StringList(TranslationFile):
    """An in-memory "file" holding strings to translate.

    Repeated strings are translated once. Blank strings are left as they are.
    """

    name = "strings"

    def __init__(self, texts, context=""):
        super().__init__("<strings>")
        if isinstance(texts, (str, bytes)):
            raise TypeError("Pass a list of strings, not a single string")
        self.texts = list(texts)
        for index, text in enumerate(self.texts):
            if not isinstance(text, str):
                raise TypeError(f"Can only translate strings, got {type(text).__name__} at index {index}")
        self.context = context
        self.translations = {}

    def untranslated_units(self):
        unique = dict.fromkeys(text for text in self.texts if text.strip())
        return [TranslationUnit(key=text, source=text, context=self.context) for text in unique]

    def apply(self, key, translation):
        self.translations[key] = translation

    def save(self):
        pass

    def results(self):
        return [text if not text.strip() else self.translations.get(text) for text in self.texts]


@dataclass
class StringsResult:
    """Translations for a list of strings, in the same order.

    :ivar translations: one per input string; ``None`` where no valid
        translation came back
    :ivar rejected: ``Counter`` of reasons translations were rejected
    :ivar errors: ``Counter`` of error messages from failed batches
    """

    translations: list
    rejected: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)

    @property
    def complete(self):
        return None not in self.translations


class BaseTranslator:
    """The client and settings ``StringTranslator`` and ``FileTranslator`` share.

    :param provider: ``"openai"``, ``"anthropic"``, ``"gemini"``, ``"grok"``,
        or a dotted path to an ``LLMClient`` subclass
    :param instructions: extra instructions for every call, e.g. tone or
        terminology
    :param client_options: passed to the client, e.g. ``model``,
        ``api_base`` or ``model_params``
    """

    def __init__(self, provider="openai", api_key=None, source_language="en", instructions="",
                 batch_size=50, workers=10, **client_options):
        self.client = get_client(provider, api_key=api_key, **client_options)
        # None, as a setting left empty gives, means the default
        self.source_language = source_language or "en"
        self.instructions = instructions
        self.batch_size = batch_size
        self.workers = workers

    @classmethod
    def from_config(cls, config, **overrides):
        """Build a translator from a config dict with the keys of ``LLM_LOCALIZE``, with keyword overrides.

        Missing keys take their defaults.
        """
        config = {**DEFAULTS, **config}
        options = {
            "provider": config["PROVIDER"],
            "api_key": config["API_KEY"],
            "source_language": config["SOURCE_LANGUAGE"],
            "instructions": config["EXTRA_INSTRUCTIONS"],
            "batch_size": config["BATCH_SIZE"],
            "workers": config["WORKERS"],
            "model": config["MODEL"],
            "model_params": config["MODEL_PARAMS"],
        }
        if config["API_BASE"]:
            options["api_base"] = config["API_BASE"]
        return cls(**{**options, **overrides})


class StringTranslator(BaseTranslator):
    """Translates lists of strings with an LLM.

    ::

        translator = StringTranslator(provider="anthropic", api_key="...")

        translator.translate(["Hello", "Hi %(name)s"], "fr")
        # ["Bonjour", "Salut %(name)s"]

    Safe to share between threads; create one and reuse it. Takes the
    options of ``BaseTranslator``.
    """

    def translate(self, texts, language, context="", source_language=None, instructions=None):
        """Return the translations of ``texts`` in order, with ``None`` for any that failed.

        :param context: what the strings are, to help the model, e.g.
            "product names in a hardware store"
        :param instructions: replaces the translator's instructions for this call
        :raises FatalError: for errors every request would hit, like a bad API key
        """
        return self.translate_with_report(texts, language, context, source_language, instructions).translations

    def translate_with_report(self, texts, language, context="", source_language=None, instructions=None):
        """Like ``translate``, but also say why any translations are missing."""
        strings = StringList(texts, context)
        result = translate_file(
            strings, self.client, language,
            source_language=source_language or self.source_language,
            batch_size=self.batch_size,
            workers=self.workers,
            extra_instructions=self.instructions if instructions is None else instructions,
            cleanup=False,
        )
        return StringsResult(strings.results(), rejected=result.rejected, errors=result.errors)
