import codecs
import json
import time

import pytest

from llm_localize.engine import translate_file
from llm_localize.formats import open_file

from .fakes import FakeClient

STRINGS = r'''/* Greeting on the home screen */
"welcome" = "Welcome, %@!";

"Cancel" = "Cancel";

// Shown in a dialog
unquoted_key = "Say \"hi\"\nnow";
"empty" = "";
'''


def write(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


@pytest.fixture
def lproj(tmp_path):
    write(tmp_path / "en.lproj" / "Localizable.strings", STRINGS)
    return tmp_path


class TestStrings:

    @pytest.mark.parametrize("source", ["en.lproj", "Base.lproj"])
    def test_source_from_path(self, tmp_path, source):
        write(tmp_path / source / "Localizable.strings", STRINGS)

        strings_file = open_file(tmp_path / "pt-BR.lproj" / "Localizable.strings", source_language="en")

        assert strings_file.language == "pt-BR"
        assert strings_file.source_path == str(tmp_path / source / "Localizable.strings")

    def test_units(self, lproj):
        units = open_file(lproj / "fr.lproj" / "Localizable.strings").untranslated_units()

        assert [(unit.key, unit.source, unit.context) for unit in units] == [
            ("welcome", "Welcome, %@!", "Greeting on the home screen; Key: welcome"),
            ("Cancel", "Cancel", ""),
            ("unquoted_key", 'Say "hi"\nnow', "Shown in a dialog; Key: unquoted_key"),
        ]

    def test_creates_the_target_file(self, lproj):
        path = lproj / "fr.lproj" / "Localizable.strings"

        assert translate_file(open_file(path), FakeClient(), "fr").translated == 3

        assert path.read_text(encoding="utf-8") == r'''/* Greeting on the home screen */
"welcome" = "T: Welcome, %@!";

"Cancel" = "T: Cancel";

/* Shown in a dialog */
"unquoted_key" = "T: Say \"hi\"\nnow";
'''
        assert open_file(path).untranslated_units() == []

    def test_fills_in_an_existing_utf16_file(self, lproj):
        existing = '/* Mine */\n"Cancel" = "Annuler";\n"welcome" = "";'
        path = write(lproj / "fr.lproj" / "Localizable.strings", existing, "utf-16")

        translate_file(open_file(path), FakeClient(), "fr")

        data = path.read_bytes()
        assert data.startswith(codecs.BOM_UTF16)
        assert data.decode("utf-16") == (
            '/* Mine */\n"Cancel" = "Annuler";\n"welcome" = "T: Welcome, %@!";\n'
            '\n/* Shown in a dialog */\n"unquoted_key" = "T: Say \\"hi\\"\\nnow";\n'
        )

    def test_characters_beyond_utf16_written_as_escape_pairs(self, tmp_path):
        write(tmp_path / "en.lproj" / "Localizable.strings",
              '"\\UD83D\\UDE00 smile" = "Smile";\n"party" = "Party \\UD83C\\UDF89";\n"lone" = "\\UD83D";\n')
        target = write(tmp_path / "fr.lproj" / "Localizable.strings", '"greeting" = "Bonjour";\n')
        units = open_file(target).untranslated_units()

        result = translate_file(open_file(target), FakeClient(), "fr")

        assert [unit.source for unit in units] == ["Smile", "Party 🎉", "\ud83d"]
        # A lone surrogate can't be written as text, so its translation is rejected, and the rest saved
        assert (result.failed_batches, dict(result.rejected)) == (0, {"encoding": 1})
        assert target.read_text() == ('"greeting" = "Bonjour";\n\n"😀 smile" = "T: Smile";\n\n'
                                      '"party" = "T: Party 🎉";\n')

    def test_octal_escapes_are_read(self, tmp_path):
        write(tmp_path / "en.lproj" / "Localizable.strings", '"\\101pple" = "Apple\\012pie";\n')
        target = tmp_path / "fr.lproj" / "Localizable.strings"

        translate_file(open_file(target), FakeClient(), "fr")

        # The key is the one the app looks up, "Apple"
        assert target.read_text() == '"Apple" = "T: Apple\\npie";\n'

    def test_invalid_file(self, lproj):
        write(lproj / "fr.lproj" / "Localizable.strings", '"Cancel" = "Annuler"')

        with pytest.raises(ValueError, match="not a valid .strings file"):
            open_file(lproj / "fr.lproj" / "Localizable.strings").untranslated_units()

    def test_a_unicode_escape_without_its_digits_is_invalid(self, lproj):
        write(lproj / "fr.lproj" / "Localizable.strings", '"Cancel\\uZZZZ" = "Annuler";\n')

        with pytest.raises(ValueError, match=r"not a valid .strings file near .*: \\u is not followed by four"):
            open_file(lproj / "fr.lproj" / "Localizable.strings").untranslated_units()


def string_unit(value, state="translated"):
    return {"stringUnit": {"state": state, "value": value}}


CATALOG = {
    "sourceLanguage": "en",
    "strings": {
        "Hello %@": {"comment": "Greeting", "localizations": {"fr": string_unit("Bonjour %@")}},
        "Save": {},
        "%lld files": {"localizations": {"en": {"variations": {"plural": {
            "one": string_unit("%lld file"), "other": string_unit("%lld files")}}}}},
        "Device": {"localizations": {"en": {"variations": {"device": {"iphone": string_unit("Phone")}}}}},
        "API": {"shouldTranslate": False},
        "Stale": {"localizations": {"de": string_unit("Alt", state="new")}},
    },
    "version": "1.0",
}


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "Localizable.xcstrings"
    path.write_text(json.dumps(CATALOG, indent=2, separators=(",", " : ")) + "\n", encoding="utf-8")
    return path


class TestXcstrings:

    def test_needs_a_language(self, catalog):
        with pytest.raises(ValueError, match="pass the one to translate to with --lang"):
            open_file(catalog).untranslated_units()

    def test_targets_it_cant_write_back_are_left_alone(self, tmp_path):
        catalog = {"sourceLanguage": "en", "strings": {
            "Device": {"localizations": {"fr": {"variations": {"device": {"iphone": string_unit("Tél")}}}}},
            "Sub": {"localizations": {"fr": {"substitutions": {"n": {}}, **string_unit("")}}},
            "Plain": {"localizations": {"fr": {"variations": {"plural": {"other": string_unit("")}}}}},
        }}
        path = tmp_path / "L.xcstrings"
        path.write_text(json.dumps(catalog))

        assert open_file(path, language="fr").untranslated_units() == []

    def test_languages_stay_in_alphabetical_order(self, catalog):
        translate_file(open_file(catalog, language="de"), FakeClient(), "de")

        assert list(json.loads(catalog.read_text())["strings"]["Hello %@"]["localizations"]) == ["de", "fr"]


def test_unfinished_comments_are_refused_in_linear_time(tmp_path):
    write(tmp_path / "en.lproj" / "Localizable.strings", "/*x " * 200000)

    started = time.perf_counter()
    with pytest.raises(ValueError, match="not a valid .strings file"):
        open_file(tmp_path / "fr.lproj" / "Localizable.strings").untranslated_units()
    assert time.perf_counter() - started < 1


def test_a_line_comment_holding_the_end_of_a_block_comment_stays_a_line_comment(tmp_path):
    write(tmp_path / "en.lproj" / "Localizable.strings", '// Use */ to close a comment\n"hello" = "Hello";\n')
    target = tmp_path / "fr.lproj" / "Localizable.strings"

    translate_file(open_file(target), FakeClient(), "fr")

    assert target.read_text(encoding="utf-8") == '// Use */ to close a comment\n"hello" = "T: Hello";\n'
    assert open_file(target).untranslated_units() == []


def test_lines_of_line_comments_are_one_comment(tmp_path):
    write(tmp_path / "en.lproj" / "Localizable.strings",
          '/* File */\n// Submit button\n// on the form\n"a" = "Submit";\n')

    [unit] = open_file(tmp_path / "fr.lproj" / "Localizable.strings").untranslated_units()

    assert unit.context == "Submit button on the form; Key: a"


def test_a_trailing_comment_belongs_to_its_entry(tmp_path):
    write(tmp_path / "en.lproj" / "Localizable.strings",
          '"save" = "Save"; // toolbar button\n// Shown when the upload fails\n"error" = "Upload failed";\n')

    units = open_file(tmp_path / "fr.lproj" / "Localizable.strings").untranslated_units()

    assert [unit.context for unit in units] == ["Key: save", "Shown when the upload fails; Key: error"]
