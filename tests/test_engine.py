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
from llm_localize.units import PluralForm, TranslationUnit
from llm_localize.validation import find_problem

SPANISH_FORMS = (
    PluralForm(0, "used when n is 1", singular=True),
    PluralForm(1, "used when n is 1000000, 2000000"),
    PluralForm(2, "used when n is 0, 2, 3, ..."),
)
CASES = TranslationUnit(
    key="cases", source="%(count)s case", plural_source="%(count)s cases", plural_forms=SPANISH_FORMS)


def test_build_system_prompt():
    prompt = build_system_prompt("fr", "en", "Format rules.", "Be formal.")

    assert "from English to French" in prompt
    assert "File format rules: Format rules." in prompt
    assert "Additional instructions: Be formal." in prompt


def test_plural_reply_keys_are_the_form_keys_sent():
    prompt = build_system_prompt("fr", "en")

    assert '"forms": {"one":' in prompt and '"<key>:one"' in prompt and '"<key>:0"' not in prompt


def test_build_system_prompt_unknown_language():
    assert "to some_lang_code" in build_system_prompt("some_lang_code")


def test_format_batch():
    batch = {
        "0": TranslationUnit(key="a", source="Hello"),
        "1": TranslationUnit(key="b", source="May", context="month"),
        "2": CASES,
    }

    assert json.loads(format_batch(batch)) == {
        "0": "Hello",
        "1": {"text": "May", "context": "month"},
        "2": {
            "singular": "%(count)s case",
            "plural": "%(count)s cases",
            "forms": {
                "0": "used when n is 1",
                "1": "used when n is 1000000, 2000000",
                "2": "used when n is 0, 2, 3, ...",
            },
        },
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
        batch = {"0": TranslationUnit(key="a", source="Hello"), "1": CASES}
        response = json.dumps({
            "0": "Hola",
            "1:0": "%(count)s caso", "1:1": "%(count)s de casos", "1:2": "%(count)s casos",
        })

        assert parse_response(response, batch, find_problem) == ({
            "0": "Hola",
            "1": {0: "%(count)s caso", 1: "%(count)s de casos", 2: "%(count)s casos"},
        }, Counter())

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

    @pytest.mark.parametrize("output, reason", [
        pytest.param({"0:0": "%(count)s caso", "0:2": "%(count)s casos"}, "missing", id="missing-form"),
        pytest.param({"0:0": "%(count)s caso", "0:1": "", "0:2": "%(count)s casos"}, "missing", id="empty-form"),
        pytest.param({"0:0": "%(count)s caso", "0:1": " ", "0:2": "%(count)s casos"}, "missing", id="blank-form"),
        pytest.param({"0:0": "%(count)s caso", "0:1": "%(cuenta)s de casos", "0:2": "%(count)s casos"},
                     "placeholders", id="bad-placeholder"),
        pytest.param({"0": "%(count)s casos"}, "missing", id="plain-key"),
    ])
    def test_rejected_plural(self, output, reason):
        assert parse_response(json.dumps(output), {"0": CASES}, find_problem) == ({}, Counter({reason: 1}))

    def test_counts_each_reason(self):
        batch = {str(i): TranslationUnit(key=str(i), source=f"Hello {{name}} {i}") for i in range(4)}
        output = {"0": "Hola {name} 0", "1": "Hola 1", "2": "Hola {nombre} 2"}

        translations, rejected = parse_response(json.dumps(output), batch, find_problem)

        assert translations == {"0": "Hola {name} 0"}
        assert rejected == Counter({"placeholders": 2, "missing": 1})

    @pytest.mark.parametrize("keys", [("0:one", "0:other"), ("0:0", "0:1")])
    def test_category_forms_by_key_or_by_position(self, keys):
        unit = TranslationUnit(
            key="a", source="{{count}} item", plural_source="{{count}} items",
            plural_forms=(PluralForm("one", "used when n is 1", singular=True), PluralForm("other", "other")),
        )
        response = json.dumps({keys[0]: "{{count}} article", keys[1]: "{{count}} articles"})

        assert parse_response(response, {"0": unit}, find_problem)[0] == {
            "0": {"one": "{{count}} article", "other": "{{count}} articles"},
        }

    def test_singular_form_checked_against_singular_source(self):
        unit = TranslationUnit(
            key="a", source="One case", plural_source="%(count)s cases",
            plural_forms=(PluralForm(0, "used when n is 1", singular=True), PluralForm(1, "other")),
        )
        response = json.dumps({"0:0": "Un caso", "0:1": "%(count)s casos"})

        assert parse_response(response, {"0": unit}, find_problem)[0] == {
            "0": {0: "Un caso", 1: "%(count)s casos"},
        }

    def test_json_wrapped_in_a_code_fence(self):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response('```json\n{"0": "Hola"}\n```', batch, find_problem)[0] == {"0": "Hola"}

    def test_uses_given_checker(self):
        batch = {"0": TranslationUnit(key="a", source="Hello")}

        assert parse_response(json.dumps({"0": "Hola"}), batch, lambda s, t: "too short") == (
            {}, Counter({"too short": 1}))
