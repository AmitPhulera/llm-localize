import pytest

from llm_localize.plurals import plural_categories, plural_forms


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

    def test_only_exactly_one_is_singular(self):
        assert [form.singular for form in plural_forms("uk")] == [False, False, False, False]
        assert [form.index for form in plural_forms("pt-PT") if form.singular] == ["one"]
