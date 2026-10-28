import json
from collections import Counter

import pytest

from llm_localize import StringTranslator
from llm_localize.providers.base import FatalError

from .fakes import FakeClient, ScriptedClient


def translator_with(client, **kwargs):
    translator = StringTranslator(provider="tests.fakes.FakeClient", api_key="k", **kwargs)
    translator.client = client
    return translator


def test_translates_in_order():
    translator = StringTranslator(provider="tests.fakes.FakeClient", api_key="k")

    assert translator.translate(["Hello", "Hi %(name)s", "Bye"], "fr") == ["T: Hello", "T: Hi %(name)s", "T: Bye"]


def test_repeated_and_blank_strings():
    client = FakeClient()
    translator = translator_with(client)

    assert translator.translate(["Hello", "", "  ", "Hello"], "fr") == ["T: Hello", "", "  ", "T: Hello"]
    assert json.loads(client.calls[0][1]) == {"0": "Hello"}


def test_nothing_to_translate_makes_no_calls():
    client = FakeClient()

    assert translator_with(client).translate(["", " "], "fr") == ["", " "]
    assert client.calls == []


def test_batches_in_parallel():
    client = FakeClient()
    translator = translator_with(client, batch_size=2, workers=3)

    translations = translator.translate([f"m{i}" for i in range(7)], "fr")

    assert translations == [f"T: m{i}" for i in range(7)]
    assert len(client.calls) == 4


def test_failures_are_none_with_a_report():
    client = ScriptedClient([{"0": "Hola", "1": "Adiós {nombre}"}, RuntimeError("boom")])
    translator = translator_with(client, batch_size=2, workers=1)

    report = translator.translate_with_report(["Hello", "Bye {name}", "Yes"], "es")

    assert report.translations == ["Hola", None, None]
    assert report.rejected == Counter({"placeholders": 1})
    assert report.errors == Counter({"RuntimeError: boom": 1})
    assert not report.complete


def test_fatal_errors_raise():
    translator = translator_with(ScriptedClient([FatalError("HTTP 401: invalid key", status=401)]))

    with pytest.raises(FatalError):
        translator.translate(["Hello"], "es")


def test_context_and_instructions_reach_the_prompt():
    client = FakeClient()
    translator = translator_with(client, instructions="Be formal.", source_language="de")

    translator.translate(["Schraube"], "fr", context="hardware store product")
    system_prompt, user_message, _ = client.calls[0]
    assert "from German to French" in system_prompt
    assert "Additional instructions: Be formal." in system_prompt
    assert json.loads(user_message) == {"0": {"text": "Schraube", "context": "hardware store product"}}

    translator.translate(["Schraube"], "fr", instructions="Be casual.")
    assert "Additional instructions: Be casual." in client.calls[1][0]
