import pytest

from llm_localize.plurals import plural_categories


class TestPluralForms:

    @pytest.mark.parametrize("language, categories", [
        ("en", ["one", "other"]),
        ("fr", ["one", "many", "other"]),
        ("ar", ["zero", "one", "two", "few", "many", "other"]),
        ("zh-Hans", ["other"]),
        ("sr_Latn", ["one", "few", "other"]),
    ])
    def test_categories(self, language, categories):
        assert list(plural_categories(language)) == categories
