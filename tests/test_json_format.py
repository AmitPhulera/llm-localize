import json

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file

from .fakes import FakeClient

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

    def test_explicit_source_and_language(self, locales):
        path = locales.dir / "french-strings.json"

        json_file = open_file(path, language="fr", source_path=locales.dir / "en.json")

        assert (json_file.language, json_file.source_path) == ("fr", str(locales.dir / "en.json"))

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


class TestTranslating:

    def test_creates_the_target_file(self, locales):
        path = locales.dir / "fr.json"

        result = translate(path, source_path=locales.dir / "en.json")

        assert result.translated == 5
        assert read(path) == {
            "home": {"title": "T: Welcome", "greeting": "T: Hi {{name}}"},
            "items_one": "T: {{count}} item",
            "items_other": "T: {{count}} items",
            "show_other": "T: Show other",
        }
        assert path.read_text().startswith('{\n  "home": {\n    "title"')
        assert path.read_text().endswith("}\n")

    def test_cli_with_source(self, locales):
        source = locales("base/strings.json", {"hello": "Hello"})

        main([str(locales.dir / "out.json"), "--lang", "es", "--source", str(source),
              "--provider", "tests.fakes.FakeClient", "--api-key", "k"])

        assert read(locales.dir / "out.json") == {"hello": "T: Hello"}
