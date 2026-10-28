import pytest

from llm_localize.engine import build_system_prompt, make_batches
from llm_localize.units import TranslationUnit


def test_build_system_prompt():
    prompt = build_system_prompt("fr", "en", "Format rules.", "Be formal.")

    assert "from English to French" in prompt
    assert "File format rules: Format rules." in prompt
    assert "Additional instructions: Be formal." in prompt


def test_build_system_prompt_unknown_language():
    assert "to some_lang_code" in build_system_prompt("some_lang_code")


def test_make_batches_needs_a_positive_size():
    with pytest.raises(ValueError, match="at least 1"):
        make_batches([TranslationUnit(key="a", source="Hello")], 0)


def test_make_batches():
    units = [TranslationUnit(key=k, source=k) for k in "abc"]

    assert make_batches(units, 2) == [{"0": units[0], "1": units[1]}, {"0": units[2]}]
