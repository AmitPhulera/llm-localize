
import pytest

from llm_localize.engine import make_batches
from llm_localize.units import TranslationUnit


def test_make_batches_needs_a_positive_size():
    with pytest.raises(ValueError, match="at least 1"):
        make_batches([TranslationUnit(key="a", source="Hello")], 0)


def test_make_batches():
    units = [TranslationUnit(key=k, source=k) for k in "abc"]

    assert make_batches(units, 2) == [{"0": units[0], "1": units[1]}, {"0": units[2]}]
