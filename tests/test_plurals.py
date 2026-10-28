import pytest

from llm_localize.formats.po.plurals import nplurals_from_header


def test_no_more_plural_forms_than_a_language_could_have():
    assert nplurals_from_header("nplurals=10; plural=0;") == 10
    with pytest.raises(ValueError, match="no language has 11 plural forms"):
        nplurals_from_header("nplurals=11; plural=0;")
