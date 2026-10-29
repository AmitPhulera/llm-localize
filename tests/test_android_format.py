import time
from xml.parsers import expat

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.android import AndroidFile

from .fakes import FakeClient, ScriptedClient

SOURCE = r'''<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2" xmlns:tools="http://schemas.android.com/tools">
    <!-- Shown on the home screen -->
    <string name="app_name">Notes</string>
    <string name="welcome">Don\'t forget, %1$s!</string>
    <string name="api_key" translatable="false">abc123</string>
    <string name="link">@string/app_name</string>
    <string name="bold">Tap <b>Save</b> &amp; go</string>
    <string name="count">You have <xliff:g id="count" example="3">%d</xliff:g> notes</string>
    <plurals name="notes">
        <item quantity="one">%d note</item>
        <item quantity="other">%d notes</item>
    </plurals>
    <string-array name="colors"><item>Red</item></string-array>
    <string name="quoted">"  It's spaced  "</string>
</resources>
'''


@pytest.fixture
def res(tmp_path):
    (tmp_path / "res" / "values").mkdir(parents=True)
    (tmp_path / "res" / "values" / "strings.xml").write_text(SOURCE, encoding="utf-8")
    return tmp_path / "res"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestFindingFiles:

    @pytest.mark.parametrize("target, language, source", [
        ("values-fr/strings.xml", "fr", "values/strings.xml"),
        ("values-pt-rBR/strings.xml", "pt-BR", "values/strings.xml"),
        ("values-b+sr+Latn/strings.xml", "sr-Latn", "values/strings.xml"),
        ("values-fr-land/strings.xml", "fr", "values-land/strings.xml"),
    ])
    def test_language_and_source_from_path(self, tmp_path, target, language, source):
        write(tmp_path / source, SOURCE)

        android_file = open_file(tmp_path / target)

        assert (android_file.language, android_file.source_path) == (language, str(tmp_path / source))

    def test_other_xml_needs_a_source(self, tmp_path):
        with pytest.raises(ValueError, match="pass it with --source"):
            open_file(tmp_path / "layout" / "main.xml", language="fr").untranslated_units()


class TestTranslating:

    def test_units(self, res):
        units = {unit.key: unit for unit in open_file(res / "values-fr" / "strings.xml").untranslated_units()}

        assert list(units) == [
            "string/app_name", "string/welcome", "string/bold", "string/count", "plurals/notes", "string/quoted"]
        assert units["string/app_name"].context == "Key: app_name. Comment: Shown on the home screen"
        assert units["string/welcome"].source == "Don't forget, %1$s!"
        assert units["string/bold"].source == "Tap <b>Save</b> &amp; go"
        assert units["string/quoted"].source == "  It's spaced  "
        notes = units["plurals/notes"]
        assert (notes.source, notes.plural_source) == ("%d note", "%d notes")
        assert [form.index for form in notes.plural_forms] == ["one", "many", "other"]

    def test_creates_the_target_file(self, res):
        path = res / "values-fr" / "strings.xml"

        result = translate_file(open_file(path), FakeClient(), "fr")

        assert result.translated == 6
        assert path.read_text(encoding="utf-8") == r'''<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2" xmlns:tools="http://schemas.android.com/tools">
    <string name="app_name">T: Notes</string>
    <string name="welcome">T: Don\'t forget, %1$s!</string>
    <string name="bold">T: Tap <b>Save</b> &amp; go</string>
    <string name="count">T: You have <xliff:g id="count" example="3">%d</xliff:g> notes</string>
    <plurals name="notes">
        <item quantity="one">T: %d notes</item>
        <item quantity="many">T: %d notes</item>
        <item quantity="other">T: %d notes</item>
    </plurals>
    <string name="quoted">"T:   It's spaced  "</string>
</resources>
'''
        assert open_file(path).untranslated_units() == []

    def test_keeps_an_existing_file_and_fills_it_in(self, res):
        existing = '''<?xml version="1.0" encoding="utf-8"?>
<!-- Translated by hand -->
<resources>
  <string name="app_name"></string>
  <string name="welcome">N\\'oublie pas, %1$s !</string>
  <string name="bold"/>
  <string name="old">Gardé</string>
</resources>
'''
        path = write(res / "values-fr" / "strings.xml", existing)

        translate_file(open_file(path), FakeClient(), "fr")

        text = path.read_text(encoding="utf-8")
        assert text.startswith('''<?xml version="1.0" encoding="utf-8"?>
<!-- Translated by hand -->
<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2">
  <string name="app_name">T: Notes</string>
  <string name="welcome">N\\'oublie pas, %1$s !</string>
  <string name="bold">T: Tap <b>Save</b> &amp; go</string>
  <string name="old">Gardé</string>
  <string name="count">''')
        quoted = '<string name="quoted">"T:   It\'s spaced  "</string>'
        assert text.endswith(f"</plurals>\n  {quoted}\n</resources>\n")
        assert '\n  <plurals name="notes">\n    <item quantity="one">' in text
        # With namespaces checked, so a prefix like xliff: must be declared
        expat.ParserCreate(namespace_separator=" ").Parse(text.encode(), True)

    @pytest.mark.parametrize("target", ["<resources/>", "<resources></resources>", ""])
    def test_targets_without_strings(self, res, target):
        path = write(res / "values-fr" / "strings.xml", target)

        translate_file(open_file(path), FakeClient(), "fr")

        text = path.read_text(encoding="utf-8")
        expat.ParserCreate(namespace_separator=" ").Parse(text.encode(), True)
        assert text.count("<string ") == 5 and text.count("<plurals ") == 1

    @pytest.mark.parametrize("tag", ["string", "plurals"])
    def test_strings_the_target_marks_untranslatable_are_left_alone(self, res, tag):
        kept = (f'<{tag} name="{"app_name" if tag == "string" else "notes"}" translatable="false">'
                + ("Notes" if tag == "string" else '<item quantity="other">%d notes</item>') + f"</{tag}>")
        path = write(res / "values-fr" / "strings.xml", f"<resources>\n    {kept}\n</resources>\n")

        translate_file(open_file(path), FakeClient(), "fr")

        text = path.read_text(encoding="utf-8")
        assert kept in text
        assert text.count('name="app_name"') == 1 and text.count('name="notes"') == 1

    def test_plural_forms_already_translated_are_kept(self, tmp_path):
        write(tmp_path / "res" / "values" / "strings.xml", '<resources><plurals name="files">'
              '<item quantity="one">%d file</item><item quantity="other">%d files</item></plurals></resources>')
        mine = '<item quantity="one">%d файл</item><item quantity="other">%d файла</item>'
        target = write(tmp_path / "res" / "values-ru" / "strings.xml",
                       f'<resources><plurals name="files">{mine}</plurals></resources>')

        translate_file(open_file(target), FakeClient(), "ru")

        text = target.read_text(encoding="utf-8")
        assert '<item quantity="one">%d файл</item>' in text and '<item quantity="other">%d файла</item>' in text
        assert '<item quantity="few">T: %d files</item>' in text
        assert '<item quantity="many">T: %d files</item>' in text

    def test_the_targets_own_attributes_are_kept(self, tmp_path):
        write(tmp_path / "res" / "values" / "strings.xml",
              '<resources><string name="x">100% %s</string></resources>')
        target = write(tmp_path / "res" / "values-fr" / "strings.xml",
                       '<resources><string name="x" formatted="false"></string></resources>')

        translate_file(open_file(target), FakeClient(), "fr")

        assert '<string name="x" formatted="false">T: 100% %s</string>' in target.read_text(encoding="utf-8")

    def test_cdata_keeps_its_ampersands(self, tmp_path):
        write(tmp_path / "res" / "values" / "strings.xml",
              '<resources><string name="c"><![CDATA[<b>Bold</b> & co]]></string></resources>')
        target = tmp_path / "res" / "values-fr" / "strings.xml"

        translate_file(open_file(target), FakeClient(prefix=""), "fr")

        assert '<string name="c"><![CDATA[<b>Bold</b> & co]]></string>' in target.read_text(encoding="utf-8")

    def test_a_reference_in_the_target_counts_as_translated(self, res):
        alias = '<string name="app_name">@string/brand</string>'
        path = write(res / "values-fr" / "strings.xml", f"<resources>\n    {alias}\n</resources>\n")

        units = open_file(path).untranslated_units()
        translate_file(open_file(path), FakeClient(), "fr")

        assert "app_name" not in [unit.key.split("/")[1] for unit in units]
        assert alias in path.read_text(encoding="utf-8")

    def test_escapes_what_the_model_writes(self, res):
        client = ScriptedClient([{
            "0": 'L\'appli "Notes"',
            "1": "@ toi, %1$s",
            "2": "Touchez <b>Enregistrer</b> & go",
            "3": 'Vous avez <xliff:g id="count" example="3">%d</xliff:g> notes',
            "4:one": "%d note", "4:many": "%d notes", "4:other": "%d notes",
            "5": "  C'est espacé  ",
        }])
        path = res / "values-fr" / "strings.xml"

        translate_file(open_file(path), client, "fr")

        text = path.read_text(encoding="utf-8")
        assert r'<string name="app_name">L\'appli \"Notes\"</string>' in text
        assert r'<string name="welcome">\@ toi, %1$s</string>' in text
        assert '<string name="bold">Touchez <b>Enregistrer</b> &amp; go</string>' in text
        assert '<string name="quoted">"  C\'est espacé  "</string>' in text

    def test_broken_xml_is_rejected(self, res):
        android_file = AndroidFile(res / "values-fr" / "strings.xml")

        assert android_file.find_problem("Tap <b>Save</b> &amp; go", "Touchez <b>Enregistrer</b> & go") is None
        assert android_file.find_problem("A or B", "A < B") == "XML"
        assert android_file.find_problem("Tap <b>Save</b>", "Touchez <B>Enregistrer</B>") == "XML tags"

    def test_invalid_target(self, res):
        write(res / "values-fr" / "strings.xml", "<resources><string>")

        with pytest.raises(ValueError, match="not valid XML"):
            open_file(res / "values-fr" / "strings.xml").untranslated_units()

    def test_cli(self, res, capsys):
        path = res / "values-de" / "strings.xml"

        assert main([str(path), "--provider", "tests.fakes.FakeClient", "--api-key", "k"]) == 0

        assert capsys.readouterr().out == f"{path} (de): translated 6 of 6\n"


def test_source_found_for_a_language_the_tables_dont_list(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", '<resources><string name="a">Hi</string></resources>')

    android = open_file(tmp_path / "res" / "values-rw" / "strings.xml", language="rw")

    assert android.source_path == str(tmp_path / "res" / "values" / "strings.xml")


def test_a_source_with_no_strings_gives_a_well_formed_target(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", "<resources/>")
    target = tmp_path / "res" / "values-fr" / "strings.xml"

    open_file(target).save()

    assert target.read_text(encoding="utf-8") == ('<?xml version="1.0" encoding="utf-8"?>\n'
                                                  '<resources>\n</resources>\n')


def test_nested_markup_takes_linear_time(tmp_path):
    depth = 100000
    write(tmp_path / "res" / "values" / "strings.xml",
          '<resources><string name="x">' + "<b>" * depth + "Hi" + "</b>" * depth + "</string></resources>")

    started = time.perf_counter()
    open_file(tmp_path / "res" / "values-fr" / "strings.xml").untranslated_units()
    assert time.perf_counter() - started < 2


def test_markup_from_entities_takes_linear_time(tmp_path):
    # Each element from an entity is placed at its reference, so finding its tag's end scanned on
    write(tmp_path / "res" / "values" / "strings.xml", '<!DOCTYPE resources [<!ENTITY br "<br/>">]>'
          '<resources><string name="x">' + "&br;" * 50000 + "</string></resources>")

    started = time.perf_counter()
    open_file(tmp_path / "res" / "values-fr" / "strings.xml").untranslated_units()
    assert time.perf_counter() - started < 2


def test_a_resource_from_an_entity_is_refused(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml",
          """<!DOCTYPE resources [<!ENTITY s '<string name="a">A</string>'>]><resources>&s;</resources>""")

    with pytest.raises(ValueError, match="from an entity"):
        open_file(tmp_path / "res" / "values-fr" / "strings.xml").untranslated_units()


def test_quoted_parts_anywhere_are_android_syntax(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml",
          '<resources><string name="q">"Hello" and "bye"</string></resources>')

    [unit] = open_file(tmp_path / "res" / "values-fr" / "strings.xml").untranslated_units()

    assert unit.source == "Hello and bye"


def test_plural_items_are_quoted_if_any_source_item_is(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", '<resources><plurals name="n">'
          '<item quantity="one">" %d note "</item></plurals></resources>')
    target = tmp_path / "res" / "values-fr" / "strings.xml"

    translate_file(open_file(target), ScriptedClient([{"0:one": " %d note ", "0:many": " %d notes ",
                                                       "0:other": " %d notes "}]), "fr")

    assert '<item quantity="other">" %d notes "</item>' in target.read_text(encoding="utf-8")


def test_character_references_are_checked_as_their_characters(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", '<resources><string name="a">Hello</string></resources>')
    android = open_file(tmp_path / "res" / "values-fr" / "strings.xml")

    assert android.find_problem("Hello", "Bonjour &#37;s") == "placeholders"
    assert android.find_problem("Hello", "Bonjour &#104;ttps://evil.example") == "URLs"
    assert android.find_problem("50&#37; off", "50&#37; de remise") is None


def test_a_quote_after_an_escaped_backslash_ends_the_string(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", r'<resources><string name="p">"C:\\"</string></resources>')
    target = tmp_path / "res" / "values-fr" / "strings.xml"

    [unit] = open_file(target).untranslated_units()
    translate_file(open_file(target), ScriptedClient([{"0": unit.source}]), "fr")

    assert unit.source == "C:\\\\"
    assert r'<string name="p">"C:\\"</string>' in target.read_text(encoding="utf-8")


def test_text_in_cdata_is_translated_and_its_markup_kept(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", '<resources><string name="a">Hello</string></resources>')
    android = open_file(tmp_path / "res" / "values-fr" / "strings.xml")

    assert android.find_problem("<![CDATA[<b>Hello</b>]]>", "<![CDATA[<b>Bonjour</b>]]>") is None
    assert android.find_problem("<![CDATA[<b>Hello</b>]]>", "<![CDATA[<b onclick=x()>Bonjour</b>]]>") is not None


def test_markup_escaped_for_html_from_html_is_checked(tmp_path):
    write(tmp_path / "res" / "values" / "strings.xml", '<resources><string name="a">Hello</string></resources>')
    android = open_file(tmp_path / "res" / "values-fr" / "strings.xml")
    source = "You have &lt;b>%1$d new messages&lt;/b>."

    assert android.find_problem(source, "Vous avez &lt;b>%1$d nouveaux messages&lt;/b>.") is None
    assert android.find_problem("&lt;Untitled&gt;", "&lt;Sans titre&gt;") is None
    assert android.find_problem("copy &lt;source&gt;", "copier &lt;Quelle&gt;") is None
    assert android.find_problem("&lt;b>Hi&lt;/b>", "&lt;b &#38;gt; onmouseover=alert(1)>Salut&lt;/b>") is not None
    assert android.find_problem("&lt;b>Hi&lt;/b>", r"&lt;b \u0026gt; onclick=alert(1)>Salut&lt;/b>") is not None
    assert android.find_problem("Read the guide", "Lisez le guide &lt;svg onload=alert(1)>") == "HTML tags"
    assert android.find_problem("Read the guide", "Lisez le guide &lt;script>alert(1)&lt;/script>") == "HTML tags"
    assert android.find_problem("Tap here", "Touchez &lt;x autofocus onfocus=alert(1)>ici") == "HTML tags"
    assert android.find_problem("Tap here", "Touchez &lt;x/onclick=alert(1)>ici&lt;/x>") == "HTML tags"
    assert android.find_problem("Tap here", "Touchez &lt;x.y onclick=alert(1)&gt;ici") == "HTML tags"
    # Android's \n and \t are whitespace in a tag too
    assert android.find_problem(r"Tap\nhere", r"&lt;a\nhref=//evil.example/x&gt;Touchez ici") == "HTML tags"
    padded = "Touchez &lt;x" + " hidden" * 50 + " onclick=alert(1)&gt;ici"
    assert android.find_problem("Tap here", padded) == "HTML tags"
    assert android.find_problem(source, 'Vous avez &lt;b>%1$d &lt;a href="/pay">messages&lt;/a>&lt;/b>.') \
        == "HTML tags"
