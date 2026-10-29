import pytest

from llm_localize.icu import NUMBER, Argument, Choice, ICUSyntaxError, parse
from llm_localize.plurals import plural_categories, plural_forms


class TestParse:

    def test_arguments(self):
        nodes = parse("Paid {amount, number, ::currency/EUR} on {day, date, short}")

        assert [(node.name, node.type, node.style) for node in nodes if isinstance(node, Argument)] == [
            ("amount", "number", "::currency/EUR"), ("day", "date", "short")]

    def test_choices(self):
        [choice] = parse("{n, plural, offset:1 =0 {none} one {# file} other {# files}}")

        assert (choice.type, choice.offset, list(choice.cases)) == ("plural", "1", ["=0", "one", "other"])
        assert choice.cases["one"] == [NUMBER, " file"]

    def test_hash_is_text_outside_plurals(self):
        text, argument = parse("Item #{n}")

        assert (text, argument.name) == ("Item #", "n")

    def test_hash_counts_in_a_select_inside_a_plural(self):
        [choice] = parse("{n, plural, other {{g, select, male {# his} other {# their}}}}")

        [select] = choice.cases["other"]
        assert isinstance(select, Choice) and select.cases["male"] == [NUMBER, " his"]

    def test_quoting(self):
        assert parse("It''s '{not an argument}' and '#'") == ["It's {not an argument} and '#'"]

    @pytest.mark.parametrize("text", [
        "{n, plural, one {# file}}",                   # no other case
        "{n, plural, one {# file} one {x} other {y}}",  # repeated case
        "{n, plural, one {# file} other {# files}",    # unclosed
        "Hi {}",
        "Hi {name",
        "Extra }",
        "{n, plural, other {" * 21 + "x" + "}}" * 21,  # nested deeper than any message is
    ])
    def test_syntax_errors(self, text):
        with pytest.raises(ICUSyntaxError):
            parse(text)


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
