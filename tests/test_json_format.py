import json

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.json_format import JsonFile

from .fakes import FakeClient, ScriptedClient

SOURCE = {
    "home": {"title": "Welcome", "greeting": "Hi {{name}}"},
    "items_one": "{{count}} item",
    "items_other": "{{count}} items",
    "show_other": "Show other",
    "count": 3,
    "tags": ["a", "b"],
    "empty": "",
}


@pytest.fixture
def locales(tmp_path):
    def write(name, document, indent=2):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
        return path
    write("en.json", SOURCE)
    write.dir = tmp_path
    return write


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def translate(path, client=None, **options):
    return translate_file(open_file(path, **options), client or FakeClient(), options.get("language") or "fr")


class TestFindingFiles:

    @pytest.mark.parametrize("target, language, source", [
        ("fr.json", "fr", "en.json"),
        ("fr/common.json", "fr", "en/common.json"),
        ("messages.fr.json", "fr", "messages.en.json"),
        ("pt_BR.json", "pt_BR", "en.json"),
        ("locales/zh-Hans/app.json", "zh-Hans", "locales/en/app.json"),
    ])
    def test_source_and_language_from_path(self, tmp_path, target, language, source):
        (tmp_path / source).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / source).write_text("{}")

        json_file = open_file(tmp_path / target, source_language="en")

        assert (json_file.language, json_file.source_path) == (language, str(tmp_path / source))

    def test_source_spelled_like_the_source_language(self, tmp_path):
        (tmp_path / "en_US.json").write_text("{}")

        json_file = open_file(tmp_path / "fr_FR.json", source_language="en_US")

        assert json_file.source_path == str(tmp_path / "en_US.json")

    def test_explicit_source_and_language(self, locales):
        path = locales.dir / "french-strings.json"

        json_file = open_file(path, language="fr", source_path=locales.dir / "en.json")

        assert (json_file.language, json_file.source_path) == ("fr", str(locales.dir / "en.json"))

    def test_explicit_language_django_and_cldr_dont_list(self, tmp_path):
        (tmp_path / "en.json").write_text('{"a": "Hi"}')

        json_file = open_file(tmp_path / "rw.json", language="rw", source_language="en")

        assert json_file.source_path == str(tmp_path / "en.json")

    def test_missing_source(self, tmp_path):
        with pytest.raises(ValueError, match="Can't find the en file.*--source"):
            open_file(tmp_path / "fr.json", source_language="en").untranslated_units()

    def test_keys_adding_up_to_too_much_text(self, tmp_path):
        # Each of the 10,000 strings' keys holds the 90 long keys above it: 1.8 GB of keys, from a 300 KB file
        document = {f"s{index}": "" for index in range(10_000)}
        for level in range(90):
            document = {"k" * 2000 + str(level): document}
        (tmp_path / "en.json").write_text(json.dumps(document), encoding="utf-8")

        with pytest.raises(ValueError, match="en.json has too much key text"):
            open_file(tmp_path / "fr.json", source_path=tmp_path / "en.json").untranslated_units()

    def test_source_file_has_nothing_to_translate(self, locales):
        assert open_file(locales.dir / "en.json", source_language="en").untranslated_units() == []


class TestTranslating:

    def test_creates_the_target_file(self, locales):
        path = locales.dir / "fr.json"

        result = translate(path)

        assert result.translated == 4
        assert read(path) == {
            "home": {"title": "T: Welcome", "greeting": "T: Hi {{name}}"},
            "items_one": "T: {{count}} items",
            "items_many": "T: {{count}} items",
            "items_other": "T: {{count}} items",
            "show_other": "T: Show other",
        }
        assert path.read_text().startswith('{\n  "home": {\n    "title"')
        assert path.read_text().endswith("}\n")

    def test_fills_in_only_what_is_missing(self, locales):
        path = locales("fr.json", {"extra": "Gardé", "home": {"title": "Bienvenue", "greeting": ""}}, indent=4)

        translate(path)

        document = read(path)
        assert document["home"] == {"title": "Bienvenue", "greeting": "T: Hi {{name}}"}
        assert list(document) == ["home", "items_one", "items_many", "items_other", "show_other", "extra"]
        assert path.read_text().startswith('{\n    "home"')

    def test_plural_forms_already_translated_are_kept(self, locales):
        target = locales("ru.json", {"items_one": "{{count}} вещь", "items_other": "{{count}} вещи"})

        translate(target, language="ru")

        items = {key: value for key, value in read(target).items() if key.startswith("items_")}
        assert items == {"items_one": "{{count}} вещь", "items_few": "T: {{count}} items",
                         "items_many": "T: {{count}} items", "items_other": "{{count}} вещи"}

    def test_plurals_get_the_target_languages_categories(self, locales):
        client = FakeClient()

        translate(locales.dir / "ru.json", client, language="ru")

        document = read(locales.dir / "ru.json")
        assert [key for key in document if key.startswith("items_")] == [
            "items_one", "items_few", "items_many", "items_other"]
        request = next(json.loads(call[1]) for call in client.calls if "items" in call[1])
        plural = next(value for value in request.values() if isinstance(value, dict) and "forms" in value)
        assert list(plural["forms"]) == ["one", "few", "many", "other"]
        assert plural["context"] == "Key: items"

    def test_plural_translated_only_when_every_category_is(self, locales):
        path = locales("ru.json", {"items_one": "{{count}} элемент", "items_other": "{{count}} элемента"})

        units = open_file(path, source_language="en").untranslated_units()

        assert "items" in [json.loads(unit.key)[-1] for unit in units]

    def test_context_and_instructions(self, locales):
        client = FakeClient()

        translate(locales.dir / "fr.json", client)

        system_prompt, user_message, _ = client.calls[0]
        assert json.loads(user_message)["0"] == {"text": "Welcome", "context": "Key: home.title"}
        assert "plural category of the target language: one, many, other" in system_prompt

    def test_cli(self, locales, capsys):
        exit_code = main([str(locales.dir / "de.json"), "--provider", "tests.fakes.FakeClient", "--api-key", "k"])

        assert exit_code == 0
        assert read(locales.dir / "de.json")["home"]["title"] == "T: Welcome"
        assert capsys.readouterr().out == f"{locales.dir / 'de.json'} (de): translated 4 of 4\n"

    def test_cli_with_source(self, locales):
        source = locales("base/strings.json", {"hello": "Hello"})

        main([str(locales.dir / "out.json"), "--lang", "es", "--source", str(source),
              "--provider", "tests.fakes.FakeClient", "--api-key", "k"])

        assert read(locales.dir / "out.json") == {"hello": "T: Hello"}


class TestArrays:
    def test_the_prompt_says_to_keep_codes_as_they_are(self, locales):
        assert "language or locale codes" in open_file(locales.dir / "fr.json").instructions


class TestICU:
    SOURCE = {"files": "{count, plural, one {# file} other {# files}}", "hello": "Hi {name}"}
    RUSSIAN = "{count, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}"

    def test_valid_icu_translation_is_saved(self, locales):
        source = locales("icu/en.json", self.SOURCE)
        client = ScriptedClient([{"0": self.RUSSIAN, "1": "Привет {name}"}])

        result = translate_file(open_file(source.parent / "ru.json"), client, "ru")

        assert result.translated == 2
        assert read(source.parent / "ru.json")["files"] == self.RUSSIAN

    @pytest.mark.parametrize("translation, reason", [
        ("{count, plural, one {# файл} other {# файлов}}", "plural forms"),
        ("{n, plural, one {# файл} few {# файла} many {# файлов} other {# файла}}", "ICU arguments"),
        ("{count, plural, one {# файл} few {# файла} many {# файлов} other {# файла}", "ICU syntax"),
    ])
    def test_broken_icu_is_rejected(self, locales, translation, reason):
        source = locales("icu/en.json", self.SOURCE)

        result = translate_file(open_file(source.parent / "ru.json"),
                                ScriptedClient([{"0": translation, "1": "Привет {name}"}]), "ru")

        assert dict(result.rejected) == {reason: 1}

    def test_find_problem_uses_icu_rules_only_for_icu_messages(self, locales):
        json_file = JsonFile(locales.dir / "fr.json")

        assert json_file.find_problem("Hi {name}", "Salut {nom}") == "placeholders"
        assert json_file.find_problem(self.SOURCE["files"], "{count, plural, one {# fichier} other {# x}}") \
            == "plural forms"


class TestReviewFixes:

    def test_nesting_references_are_kept(self, locales):
        json_file = JsonFile(locales.dir / "fr.json")

        assert json_file.find_problem("Use $t(common.save)", "Utilisez $t(common.save)") is None
        assert json_file.find_problem("Use $t(common.save)", "Utilisez $t(common.delete)") == "placeholders"
        assert json_file.find_problem('See $t(items, {"count": 2})', "Voir $t(items)") == "placeholders"

    def test_icu_apostrophes_are_explained(self, locales):
        assert "l''{app}" in JsonFile(locales.dir / "fr.json").instructions

    def test_language_is_not_taken_from_above_the_current_directory(self, tmp_path, monkeypatch):
        project = tmp_path / "de" / "project"
        (project / "locales").mkdir(parents=True)
        monkeypatch.chdir(project)

        assert open_file(project / "locales" / "messages.json").language is None
        assert open_file(project / "locales" / "fr.json").language == "fr"

    def test_outside_the_current_directory_only_nearby_directories_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path.parent / "de" / "a" / "b" / "c" / "messages.json"

        assert open_file(path).language is None


@pytest.mark.parametrize("path, language", [("locales/hi/to_trans.json", "hi"), ("my_notes.fr.json", "fr")])
def test_file_names_that_start_like_a_language_code(path, language):
    assert open_file(path).language == language
