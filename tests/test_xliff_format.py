import time
from random import Random
from xml.parsers import expat

import pytest

from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.xml_utils import line_indent

from .fakes import FakeClient

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

    def test_needs_a_language(self, xliff):
        path = xliff(XLIFF_1.replace(' target-language="fr"', ""))

        with pytest.raises(ValueError, match="pass it with --lang"):
            open_file(path).untranslated_units()


def test_prefixed_empty_target(xliff):
    path = xliff('<x:xliff xmlns:x="urn:oasis:names:tc:xliff:document:1.2" version="1.2">'
                 '<x:file target-language="fr"><x:body><x:trans-unit id="a"><x:source>Hi</x:source>'
                 "<x:target></x:target></x:trans-unit></x:body></x:file></x:xliff>")

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
                 '<x:g id="d">Bye</x:g></source><target></target></trans-unit></body></file></xliff>')

    translate_file(open_file(path), FakeClient(), "fr")

    text = path.read_text()
    assert '<target state="translated" xmlns:x="urn:oasis:names:tc:xliff:document:1.2">' in text
    assert '<target state="translated" xmlns:x="urn:x">' in text
    expat.ParserCreate(namespace_separator=" ").Parse(text, True)


def test_the_state_attribute_is_set_not_text_in_another(xliff):
    path = xliff('<xliff version="1.2"><file target-language="fr"><body><trans-unit id="a"><source>Hi</source>'
                 '<target note=\' state="new"\' state="new"></target></trans-unit></body></file></xliff>')

    translate_file(open_file(path), FakeClient(), "fr")

    assert '<target note=\' state="new"\' state="translated">T: Hi</target>' in path.read_text()


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
