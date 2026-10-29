from llm_localize.contrib.django.conf import get_config


def test_config_defaults(settings):
    settings.LLM_LOCALIZE = {}
    settings.LANGUAGE_CODE = "en-us"

    config = get_config()

    assert config["SOURCE_LANGUAGE"] == "en-us"
    assert config["LANGUAGES"] == ["es", "fr"]
    assert config["PROVIDER"] == "openai"
