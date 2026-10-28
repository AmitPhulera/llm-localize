import json
from collections import Counter

import pytest

from llm_localize.engine import (
    InvalidResponseError,
    build_system_prompt,
    format_batch,
    make_batches,
    parse_response,
)
from llm_localize.units import TranslationUnit
from llm_localize.validation import find_problem


def test_build_system_prompt():
    prompt = build_system_prompt("fr", "en", "Format rules.", "Be formal.")

    assert "from English to French" in prompt
    assert "File format rules: Format rules." in prompt
    assert "Additional instructions: Be formal." in prompt


def test_build_system_prompt_unknown_language():
    assert "to some_lang_code" in build_system_prompt("some_lang_code")


def test_format_batch():
    batch = {
        "0": TranslationUnit(key="a", source="Hello"),
        "1": TranslationUnit(key="b", source="May", context="month"),
    }

    assert json.loads(format_batch(batch)) == {
        "0": "Hello",
        "1": {"text": "May", "context": "month"},
    }


def test_format_batch_keeps_non_ascii_unescaped():
    assert "\u2014" in format_batch({"0": TranslationUnit(key="a", source="Save \u2014 now")})


def test_make_batches_needs_a_positive_size():
    with pytest.raises(ValueError, match="at least 1"):
        make_batches([TranslationUnit(key="a", source="Hello")], 0)


def test_make_batches():
    units = [TranslationUnit(key=k, source=k) for k in "abc"]

    assert make_batches(units, 2) == [{"0": units[0], "1": units[1]}, {"0": units[2]}]


class TestParseResponse:

    def test_valid(self):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response(json.dumps({"0": "Hola"}), batch, find_problem) == ({"0": "Hola"}, Counter())

    @pytest.mark.parametrize("response", ["not json", json.dumps(["Hola"]), None])
    def test_not_a_json_object(self, response):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        with pytest.raises(InvalidResponseError):
            parse_response(response, batch, find_problem)

    @pytest.mark.parametrize("output, reason", [
        ({"0": ""}, "missing"),
        ({"0": "  \n"}, "missing"),
        ({"0": 5}, "missing"),
        ({"1": "Hola"}, "missing"),
        ({"0": "Hola %s"}, "placeholders"),
    ])
    def test_rejected(self, output, reason):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response(json.dumps(output), batch, find_problem) == ({}, Counter({reason: 1}))

    def test_counts_each_reason(self):
        batch = {str(i): TranslationUnit(key=str(i), source=f"Hello {{name}} {i}") for i in range(4)}
        output = {"0": "Hola {name} 0", "1": "Hola 1", "2": "Hola {nombre} 2"}

        translations, rejected = parse_response(json.dumps(output), batch, find_problem)

        assert translations == {"0": "Hola {name} 0"}
        assert rejected == Counter({"placeholders": 2, "missing": 1})

    def test_json_wrapped_in_a_code_fence(self):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response('```json\n{"0": "Hola"}\n```', batch, find_problem)[0] == {"0": "Hola"}

    def test_uses_given_checker(self):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response(json.dumps({"0": "Hola"}), batch, lambda s, t: "too short") == (
            {}, Counter({"too short": 1}))
