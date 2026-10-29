from llm_localize.contrib.django import get_translator


def test_get_translator(settings):
    settings.LANGUAGE_CODE = "en-us"
    settings.LLM_LOCALIZE = {
        "PROVIDER": "tests.fakes.FakeClient",
        "API_KEY": "from-settings",
        "MODEL": "custom-model",
        "EXTRA_INSTRUCTIONS": "Be brief.",
        "BATCH_SIZE": 5,
    }

    translator = get_translator(workers=2)

    assert (translator.client.api_key, translator.client.model) == ("from-settings", "custom-model")
    assert (translator.source_language, translator.instructions) == ("en-us", "Be brief.")
    assert (translator.batch_size, translator.workers) == (5, 2)
    assert translator.translate(["Hello"], "fr") == ["T: Hello"]


def test_get_translator_passes_api_base(settings):
    settings.LLM_LOCALIZE = {"API_BASE": "http://localhost:11434/v1", "MODEL": "llama"}

    translator = get_translator()

    assert translator.client.api_base == "http://localhost:11434/v1"
