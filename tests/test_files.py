from llm_localize import FileTranslator


def test_from_config():
    translator = FileTranslator.from_config({"PROVIDER": "tests.fakes.FakeClient", "API_KEY": "k"}, max_messages=5)

    assert (translator.max_messages, translator.client.api_key) == (5, "k")
