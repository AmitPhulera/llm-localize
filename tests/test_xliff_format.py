import time
from random import Random
from xml.parsers import expat

import pytest

from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.xml_utils import line_indent

from .fakes import FakeClient, ScriptedClient

NAME = '<x id="INTERPOLATION" equiv-text="{{ name }}"/>'
FRENCH_ITEMS = ('{VAR_PLURAL, plural, =0 {aucun} one {un élément} many {<x id="INTERPOLATION"/> éléments} '
                'other {<x id="INTERPOLATION"/> éléments}}')

XLIFF_1 = '''<?xml version="1.0" encoding="UTF-8" ?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="en" target-language="fr" datatype="plaintext" original="ng2.template">
    <body>
      <trans-unit id="welcome" datatype="html">
        <source>Hello <x id="INTERPOLATION" equiv-text="{{ name }}"/>!</source>
        <context-group purpose="location"><context context-type="sourcefile">app.html</context></context-group>
        <note priority="1" from="description">Greeting on the home page</note>
      </trans-unit>
      <trans-unit id="save" datatype="html">
        <source>Save &amp; close</source>
        <target state="translated">Enregistrer et fermer</target>
        <alt-trans><source>Save</source><target/></alt-trans>
      </trans-unit>
      <trans-unit id="new" datatype="html">
        <source>New</source>
        <target state="new">New</target>
      </trans-unit>
      <trans-unit id="empty"><source>Empty &amp; done</source><target/></trans-unit>
      <trans-unit id="logo" translate="no"><source>ACME</source></trans-unit>
      <trans-unit id="items" datatype="html">
        <source>{VAR_PLURAL, plural, =0 {none} one {one item} other {<x id="INTERPOLATION"/> items}}</source>
      </trans-unit>
    </body>
  </file>
</xliff>
'''


@pytest.fixture
def xliff(tmp_path):
    def write(text, name="messages.fr.xlf"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path
    return write


class TestXliff1:

    def test_units(self, xliff):
        units = open_file(xliff(XLIFF_1)).untranslated_units()

        assert [unit.key for unit in units] == ["welcome", "new", "empty", "items"]
        assert units[0].source == 'Hello <x id="INTERPOLATION" equiv-text="{{ name }}"/>!'
        assert units[0].context == "Greeting on the home page; ID: welcome"
        assert units[2].source == "Empty &amp; done"

    def test_language(self, xliff):
        path = xliff(XLIFF_1)

        assert open_file(path).language == "fr"
        assert open_file(path, language="fr-CA").language == "fr-CA"

    def test_another_language_than_the_file_declares_is_refused(self, xliff):
        path = xliff(XLIFF_1)

        with pytest.raises(ValueError, match="declares its target language as fr, not de"):
            open_file(path, language="de").untranslated_units()

    def test_translates_in_place(self, xliff):
        path = xliff(XLIFF_1)
        replies = {"0": f"Bonjour {NAME} !", "1": "Nouveau", "2": "Vide & fini", "3": FRENCH_ITEMS}
        client = ScriptedClient([replies])

        result = translate_file(open_file(path), client, "fr")

        assert result.translated == 4
        assert path.read_text(encoding="utf-8") == XLIFF_1.replace(
            f"<source>Hello {NAME}!</source>\n",
            f'<source>Hello {NAME}!</source>\n        <target state="translated">Bonjour {NAME} !</target>\n',
        ).replace(
            '<target state="new">New</target>', '<target state="translated">Nouveau</target>',
        ).replace(
            "done</source><target/>", 'done</source><target state="translated">Vide &amp; fini</target>',
        ).replace(
            " items}}</source>\n",
            f' items}}}}</source>\n        <target state="translated">{FRENCH_ITEMS}</target>\n',
        )
        assert open_file(path).untranslated_units() == []

    @pytest.mark.parametrize("translation, reason", [
        (f"Bonjour {NAME.replace('INTERPOLATION', 'OTHER')} !", "XML tags"),
        ("Bonjour !", "placeholders"),
        (f"Bonjour {NAME} < !", "XML"),
    ])
    def test_broken_inline_elements_are_rejected(self, xliff, translation, reason):
        assert open_file(xliff(XLIFF_1)).find_problem(f"Hello {NAME}!", translation) == reason

    def test_icu_plural_needs_every_category(self, xliff):
        result = translate_file(open_file(xliff(XLIFF_1)), FakeClient(), "fr")

        assert (result.translated, dict(result.rejected)) == (3, {"plural forms": 1})

    def test_a_language_from_the_file_name(self, xliff):
        # As Angular names a copy of the messages.xlf extract-i18n writes, which declares no target language
        path = xliff(XLIFF_1.replace(' target-language="fr"', ""), name="messages.de.xlf")

        assert open_file(path).language == "de"
        assert [unit.key for unit in open_file(path).untranslated_units()][:1] == ["welcome"]

    def test_needs_a_language(self, xliff):
        path = xliff(XLIFF_1.replace(' target-language="fr"', ""), name="messages.xlf")

        with pytest.raises(ValueError, match="pass it with --lang"):
            open_file(path).untranslated_units()


def test_prefixed_empty_target(xliff):
    path = xliff('<x:xliff xmlns:x="urn:oasis:names:tc:xliff:document:1.2" version="1.2">'
                 '<x:file target-language="fr"><x:body><x:trans-unit id="a"><x:source>Hi</x:source><x:target/>'
                 "</x:trans-unit></x:body></x:file></x:xliff>")

    translate_file(open_file(path), FakeClient(), "fr")

    assert '<x:target state="translated">T: Hi</x:target>' in path.read_text()


def test_icu_apostrophes_are_explained(xliff):
    assert "l''{app}" in open_file(xliff(XLIFF_1)).instructions


def test_line_indent_matches_scanning_the_whole_line():
    def scanned(data, start):
        line = data[data.rfind(b"\n", 0, start) + 1:start]
        return line if line.isspace() else b""

    random = Random(0)
    for _ in range(2000):
        data = bytes(random.choice(b" \t\n\r\x0bx<") for _ in range(random.randrange(12)))
        for start in range(len(data) + 1):
            assert line_indent(data, start) == scanned(data, start), (data, start)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "iso-8859-1"])
def test_other_encodings_are_kept(xliff, encoding):
    text = XLIFF_1.replace('encoding="UTF-8"', f'encoding="{encoding.upper()}"')
    text = text.replace("Save &amp;", "Sauvé &amp;")
    path = xliff("")
    path.write_bytes(text.encode(encoding))

    assert open_file(path).untranslated_units()[0].source == f"Hello {NAME}!"
    translate_file(open_file(path), FakeClient(prefix="Ω: "), "fr")

    saved = path.read_bytes().decode(encoding)
    assert "Sauvé &amp;" in saved
    assert "&#937;: Hello" in saved if encoding == "iso-8859-1" else "Ω: Hello" in saved
    # Only the ICU plural, which the fake client doesn't give every French category, is left
    assert [unit.key for unit in open_file(path).untranslated_units()] == ["items"]


@pytest.mark.parametrize("encoding", ["punycode", "unicode-escape", "utf-7"])
def test_codecs_that_arent_xml_encodings_are_refused(xliff, encoding):
    # Python can decode these, punycode in quadratic time, but no XML document is in them
    path = xliff(XLIFF_1.replace('encoding="UTF-8"', f'encoding="{encoding}"'))

    with pytest.raises(ValueError, match=f"has an encoding XML can't be in, '{encoding}'"):
        open_file(path).untranslated_units()


ICU_WITH_NAME = ('{VAR_PLURAL, plural, =1 {one file by <x id="I" equiv-text="{{ name }}"/>} '
                 'other {<x id="C" equiv-text="{{ count }}"/> files}}')


@pytest.mark.parametrize("translation, reason", [
    ('{VAR_PLURAL, plural, =1 {un fichier de <x id="I" equiv-text="{{ name }}"/>} '
     'one {<x id="C" equiv-text="{{ count }}"/> fichier} many {<x id="C" equiv-text="{{ count }}"/> de fichiers} '
     'other {<x id="C" equiv-text="{{ count }}"/> fichiers}}', None),
    ('{VAR_PLURAL, plural, =1 {un fichier de <x id="OTHER" equiv-text="{{ name }}"/>} '
     'one {<x id="C" equiv-text="{{ count }}"/> fichier} many {<x id="C" equiv-text="{{ count }}"/> de fichiers} '
     'other {<x id="C" equiv-text="{{ count }}"/> fichiers}}', "XML tags"),
])
def test_icu_messages_with_interpolations_inside_cases(xliff, translation, reason):
    assert open_file(xliff(XLIFF_1)).find_problem(ICU_WITH_NAME, translation) == reason


def test_a_message_holding_an_icu_placeholder_isnt_taken_for_icu(xliff):
    source = 'Updated <x id="ICU" equiv-text="{minutes, plural, =0 {just now} other {later}}"/>'
    xliff_file = open_file(xliff(XLIFF_1.replace('target-language="fr"', 'target-language="ru"')))

    assert xliff_file.find_problem(source, source.replace("Updated", "Обновлено")) is None


def test_new_targets_are_named_like_their_source(xliff):
    path = xliff('<x:xliff xmlns:x="urn:oasis:names:tc:xliff:document:1.2" version="1.2">'
                 '<x:file target-language="fr"><x:body><x:trans-unit id="a"><x:source>Hello</x:source>'
                 '</x:trans-unit></x:body></x:file></x:xliff>')

    translate_file(open_file(path), FakeClient(), "fr")

    assert '<x:source>Hello</x:source><x:target state="translated">T: Hello</x:target>' in path.read_text()
    assert open_file(path).untranslated_units() == []


def test_targets_declare_the_namespaces_their_source_does(xliff):
    path = xliff('<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2"><file target-language="fr">'
                 '<body><trans-unit id="a"><source xmlns:x="urn:oasis:names:tc:xliff:document:1.2">Hello '
                 '<x:g id="b">world</x:g></source></trans-unit><trans-unit id="c"><source xmlns:x="urn:x">'
                 '<x:g id="d">Bye</x:g></source><target/></trans-unit></body></file></xliff>')

    translate_file(open_file(path), FakeClient(), "fr")

    text = path.read_text()
    assert '<target state="translated" xmlns:x="urn:oasis:names:tc:xliff:document:1.2">' in text
    assert '<target state="translated" xmlns:x="urn:x">' in text
    expat.ParserCreate(namespace_separator=" ").Parse(text, True)


def test_a_repeated_id_never_takes_another_units_key(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body>'
                 + "".join(f'<trans-unit id="{id}"><source>{text}</source></trans-unit>'
                           for id, text in [("a#2", "First"), ("a", "Second"), ("a", "Third")])
                 + "</body></file></xliff>")

    assert [unit.source for unit in open_file(path).untranslated_units()] == ["First", "Second", "Third"]


def test_character_references_are_checked_as_their_characters(xliff):
    assert open_file(xliff(XLIFF_1)).find_problem("Hello", "Bonjour &#37;s") == "placeholders"
    icu = "{n, select, yes {Hello &#37;s} other {Hello &#37;s}}"
    assert open_file(xliff(XLIFF_1)).find_problem(icu, "{n, select, yes {Salut} other {Salut}}") == "ICU arguments"


def test_escaped_markup_is_checked_as_markup(xliff):
    xliff_file = open_file(xliff(XLIFF_1))
    source = 'Read the &lt;a href="/terms"&gt;terms&lt;/a&gt;.'

    assert xliff_file.find_problem(source, 'Lisez les &lt;a href="/terms"&gt;conditions&lt;/a&gt;.') is None
    assert xliff_file.find_problem(source, 'Lisez les &lt;a href="javascript:x()"&gt;CGU&lt;/a&gt;.') == "links"
    double_decoded = "&lt;b &#38;gt; onclick=x()&gt;Hi&lt;/b&gt;"
    assert xliff_file.find_problem("&lt;b&gt;Hi&lt;/b&gt;", double_decoded) is not None


def test_inline_placeholders_may_move_past_each_other(xliff):
    xliff_file = open_file(xliff(XLIFF_1))
    shown = '<x id="INTERPOLATION" equiv-text="{{ shown }}"/>'
    total = '<x id="INTERPOLATION_1" equiv-text="{{ total }}"/>'

    assert xliff_file.find_problem(f"Showing {shown} of {total}", f"{total} 件中 {shown} 件を表示") is None
    assert xliff_file.find_problem(f"Showing {shown} of {total}", f"{total} 件中 {total} 件を表示") is not None
    # A % before one is text, as Turkish writes %50
    pct = '<x id="INTERPOLATION" equiv-text="{{ pct }}"/>'
    assert xliff_file.find_problem(f"{pct}% off", f"%{pct} indirim") is None
    # An apostrophe before a placeholder isn't ICU quoting
    icu = "{VAR_PLURAL, plural, =1 {Open %s once} other {Open %s # times}}"
    elided = "{VAR_PLURAL, plural, =1 {Ouvrir l'%s une fois} one {Ouvrir l'%s # fois} many {Ouvrir l'%s # fois} " \
             "other {Ouvrir l'%s # fois}}"
    assert xliff_file.find_problem(icu.replace("%s", shown), elided.replace("%s", shown)) is None
    # Past markup too
    welcome = '<g id="1">welcome</g>'
    assert xliff_file.find_problem(f"Hello {shown}, {welcome}", f'<g id="1">ようこそ</g>、{shown}さん') is None
    # One can't stand in for another
    assert xliff_file.find_problem(f"{shown}, {total}, {shown}", f"{total}, {shown}, {total}") == "XML tags"


def test_the_state_attribute_is_set_not_text_in_another(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><trans-unit id="a"><source>Hi</source>'
                 '<target note=\' state="new"\' state="new"></target></trans-unit></body></file></xliff>')

    translate_file(open_file(path), FakeClient(), "fr")

    assert '<target note=\' state="new"\' state="translated">T: Hi</target>' in path.read_text()


def test_a_segment_outside_a_unit_is_skipped(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><segment><source>Hello</source></segment>'
                 '<trans-unit id="a"><source>Hi</source></trans-unit>'
                 '<segment><source>Evil</source><target>X</target></segment></body></file></xliff>')

    # Neither is read, nor taken for the unit before it
    assert [(unit.key, unit.source) for unit in open_file(path).untranslated_units()] == [("a", "Hi")]


def test_files_for_different_languages_are_refused(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><trans-unit id="a">'
                 '<source>A</source></trans-unit></body></file><file target-language="de"><body>'
                 '<trans-unit id="b"><source>B</source></trans-unit></body></file></xliff>')

    with pytest.raises(ValueError, match="has files for more than one target language, fr and de"):
        open_file(path).untranslated_units()


def test_translate_no_holds_for_the_units_inside(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body>'
                 '<group translate="no"><trans-unit id="logo"><source>ACME</source></trans-unit>'
                 '<trans-unit id="tagline" translate="yes"><source>Tagline</source></trans-unit></group>'
                 '<trans-unit id="hello"><source>Hello</source></trans-unit></body></file></xliff>')

    assert [unit.key for unit in open_file(path).untranslated_units()] == ["tagline", "hello"]


def test_inline_elements_keep_their_case(xliff):
    xliff_file = open_file(xliff(XLIFF_1))

    changed = NAME.replace("<x id=", "<X ID=")

    assert xliff_file.find_problem(f"Hello {NAME}!", f"Bonjour {changed} !") == "XML tags"


def test_deep_nesting_takes_linear_time(xliff):
    depth = 20000
    path = xliff('<xliff version="1.2"><file target-language="fr"><body>' + "<group>" * depth
                 + '<trans-unit id="a"><source>Hello</source></trans-unit>' + "</group>" * depth
                 + "</body></file></xliff>")

    started = time.perf_counter()
    assert [unit.key for unit in open_file(path).untranslated_units()] == ["a"]
    assert time.perf_counter() - started < 1


def test_a_file_on_one_line_takes_linear_time(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body>'
                 + "".join(f'<trans-unit id="u{n}"> <source>x</source></trans-unit>' for n in range(40000))
                 + "</body></file></xliff>")

    started = time.perf_counter()
    open_file(path).untranslated_units()
    assert time.perf_counter() - started < 3


def test_a_new_target_goes_after_the_seg_source(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><trans-unit id="a">'
                 '<source>Hi. Bye.</source><seg-source><mrk mid="0" mtype="seg">Hi.</mrk> '
                 '<mrk mid="1" mtype="seg">Bye.</mrk></seg-source>'
                 "</trans-unit></body></file></xliff>")

    translate_file(open_file(path), FakeClient(), "fr")

    assert '</seg-source><target state="translated">T: Hi. Bye.</target></trans-unit>' in path.read_text()


def test_an_alt_trans_seg_source_doesnt_move_the_target(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><trans-unit id="a"><source>Hello</source>'
                 '<alt-trans><source>Hello!</source><seg-source><mrk mtype="seg" mid="1">Hello!</mrk></seg-source>'
                 "<target>Bonjour !</target></alt-trans></trans-unit></body></file></xliff>")

    translate_file(open_file(path), FakeClient(), "fr")

    assert '<source>Hello</source><target state="translated">T: Hello</target><alt-trans>' in path.read_text()
    assert open_file(path).untranslated_units() == []


def test_a_doctype_is_refused(xliff):
    path = xliff('<?xml version="1.0"?><!DOCTYPE xliff [<!ENTITY b "big">]><xliff version="1.2">'
                 '<file target-language="fr"><body><trans-unit id="a"><source>Hello &b;</source></trans-unit>'
                 '</body></file></xliff>')

    with pytest.raises(ValueError, match="has a DOCTYPE, which XLIFF files don't use"):
        open_file(path).untranslated_units()
