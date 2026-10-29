import pytest

from llm_localize.icu import NUMBER, Argument, Choice, ICUSyntaxError, find_problem, parse
from llm_localize.plurals import ordinal_categories, plural_categories, plural_forms

RUSSIAN = ["one", "few", "many", "other"]
FILES = "{count, plural, one {# file} other {# files}}"


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


class TestFindProblem:

    @pytest.mark.parametrize("source, translation", [
        (FILES, "{count, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}"),
        # Extra exact cases and categories the language doesn't use are allowed
        (FILES, "{count, plural, =0 {нет файлов} zero {x} one {# файл} few {# файла} many {# файлов} other {#}}"),
        ("{count, plural, =0 {No files} other {# files}}",
         "{count, plural, =0 {Нет файлов} one {# файл} few {# файла} many {# файлов} other {# файла}}"),
        ("{g, select, male {He} female {She} other {They}} replied",
         "{g, select, male {Он} female {Она} other {Они}} ответили"),
        ("{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}", "{n, selectordinal, other {#-й}}"),
        # Exact cases may be negative or decimal
        ("{n, plural, =-1 {minus one} =1.5 {one and a half} other {# files}}",
         "{n, plural, =-1 {минус один} =1.5 {полтора} one {#} few {#} many {#} other {# файла}}"),
        # Text outside a plural may keep its #
        ("Order #{id}: {n, plural, one {# item} other {# items}}",
         "Заказ #{id}: {n, plural, one {# товар} few {# товара} many {# товаров} other {# товара}}"),
        ("Hi <b>{name}</b>", "Привет <b>{name}</b>"),
        # A case may add the number: Russian "one" covers 21 and 31 too
        ("{n, plural, one {one file} other {# files}}",
         "{n, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}"),
        # A quoted '#' is text, not the number
        ("{n, plural, one {'#'1 file} other {'#'1 files}}",
         "{n, plural, one {'#'1 файл} few {'#'1 файла} many {'#'1 файлов} other {'#'1 файла}}"),
        ("{n, plural, one {<b>#</b> file} other {<b>#</b> files}}",
         "{n, plural, one {<b>#</b> файл} few {<b>#</b> файла} many {<b>#</b> файлов} other {<b>#</b>}}"),
    ])
    def test_valid(self, source, translation):
        assert find_problem(source, translation, RUSSIAN) is None

    @pytest.mark.parametrize("source, translation, reason", [
        (FILES, "{count, plural, one {# файл} other {# файлов}}", "plural forms"),
        (FILES, "{count, plural, one {#} few {#} many {#} other {#} single {#}}", "plural forms"),
        (FILES, "{count, select, one {#} few {#} many {#} other {#}}", "ICU arguments"),
        (FILES, "{n, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}", "ICU arguments"),
        (FILES, "{count, plural, one {# файл} few {# файла} many {# файлов} other {# файла}", "ICU syntax"),
        ("{count, plural, =0 {No files} other {# files}}",
         "{count, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}", "plural forms"),
        ("{g, select, male {He} other {They}}", "{g, select, female {Она} other {Они}}", "ICU select cases"),
        ("Hi {name}", "Привет {nom}", "ICU arguments"),
        ("{n, plural, one {{name} has # file} other {{name} has # files}}",
         "{n, plural, one {# файл} few {{name} # файла} many {{name} # файлов} other {{name}}}", "ICU arguments"),
        ("{n, plural, one {<b>#</b> file} other {<b>#</b> files}}",
         "{n, plural, one {<i>#</i> файл} few {# файла} many {# файлов} other {#}}", "HTML tags"),
        ("{n, plural, offset:1 one {#} other {#}}", "{n, plural, one {#} few {#} many {#} other {#}}",
         "ICU arguments"),
        # Every use of a repeated choice is checked, not only the last
        ("{g, select, male {Hi {name}} other {Hello {name}}} / {g, select, male {Bye} other {Goodbye}}",
         "{g, select, male {Salut} other {Bonjour}} / {g, select, male {Au revoir} other {Adieu}}",
         "ICU arguments"),
        ("{g, select, male {He} other {They}} said {g, select, male {his} other {their}}",
         "{g, select, bogus {Il} other {Ils}} a dit {g, select, male {son} other {leur}}", "ICU select cases"),
        # A case that shows the number can't drop it
        (FILES, "{count, plural, one {файл} few {файла} many {файлов} other {файла}}", "ICU arguments"),
        # Outside a plural, # isn't the number, so a translation can't add one
        ("{g, select, male {He} other {They}} replied", "{g, select, male {# Он} other {Они}} ответили",
         "ICU arguments"),
        ("{g, select, male {He} other {They}} has {n, plural, one {a file} other {# files}}",
         "{g, select, male {Он} other {Они}} # {n, plural, one {# файл} few {# файла} many {# файлов} other {#}}",
         "ICU arguments"),
        ("{n, plural, one {'#'1 file} other {'#'1 files}}",
         "{n, plural, one {'#'1 '#'файл} few {'#'1 файла} many {'#'1 файлов} other {'#'1 файла}}",
         "ICU arguments"),
        # A quoted literal can't stand in for an argument
        ("{n, plural, other {Hello {name}}}", "{n, plural, one {#} few {#} many {#} other {Bonjour '{name}'}}",
         "ICU arguments"),
        ("{n, plural, other {{g, select, male {# his} other {# their}}}}",
         "{n, plural, one {{g, select, male {его} other {их}}} few {#} many {#} other {#}}", "ICU arguments"),
    ])
    def test_invalid(self, source, translation, reason):
        assert find_problem(source, translation, RUSSIAN) == reason

    def test_selectordinal_needs_the_target_languages_ordinal_categories(self):
        source = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"
        english, russian = list(ordinal_categories("en")), list(ordinal_categories("ru"))

        dropped = "{n, selectordinal, other {#th}}"

        assert find_problem(source, dropped, ordinal_categories=english) == "plural forms"
        assert find_problem(source, source.replace("#", "# "), ordinal_categories=english) is None
        assert find_problem(source, "{n, selectordinal, other {#-й}}", RUSSIAN, russian) is None

    def test_source_that_isnt_icu_gets_the_generic_checks(self):
        assert find_problem("Hi {name", "Salut {name") is None
        assert find_problem("Hi %s {", "Salut {") == "placeholders"


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
