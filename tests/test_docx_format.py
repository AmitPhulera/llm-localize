import codecs
import time
import warnings
import zipfile
from xml.dom import minidom
from xml.parsers import expat

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.docx import _read

from .fakes import FakeClient, ScriptedClient

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

DOCUMENT = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document {W} {R}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Install</w:t></w:r></w:p>
<w:p><w:r w:rsidR="00A1"><w:t xml:space="preserve">Click </w:t></w:r><w:r w:rsidR="00B2"><w:t>the</w:t></w:r>\
<w:r w:rsidR="00C3"><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> Sa</w:t></w:r>\
<w:r w:rsidR="00D4"><w:rPr><w:b/></w:rPr><w:t>ve</w:t></w:r>\
<w:r><w:t xml:space="preserve"> button &amp; wait.</w:t></w:r></w:p>
<w:p><w:r><w:t>Name:</w:t><w:tab/><w:t>Value</w:t></w:r></w:p>
<w:p><w:hyperlink r:id="rId5"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>our site</w:t></w:r>\
</w:hyperlink><w:r><w:t xml:space="preserve"> has more.</w:t></w:r></w:p>
<w:p><w:fldSimple w:instr="DATE"><w:r><w:t>today</w:t></w:r></w:fldSimple>\
<w:r><w:t xml:space="preserve"> is the date</w:t></w:r></w:p>
<w:p><w:r><w:t></w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r><w:r><w:t/></w:r></w:p></w:tc></w:tr></w:tbl>
<w:sectPr/>
</w:body></w:document>'''

HEADER = f'<w:hdr {W}><w:p><w:r><w:t>Confidential</w:t></w:r></w:p></w:hdr>'

PARTS = {
    "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
    "word/document.xml": DOCUMENT,
    "word/header1.xml": HEADER,
    "word/styles.xml": f"<w:styles {W}/>",
}


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, text in PARTS.items():
            package.writestr(name, text)
    return path


def parts(path):
    with zipfile.ZipFile(path) as package:
        return {name: package.read(name).decode() for name in package.namelist()}


def test_paragraphs(report):
    units = open_file(report.parent / "fr" / "report.docx").untranslated_units()

    assert [(unit.source, unit.context) for unit in units] == [
        ("Install", ""),
        ("<g1>Click the</g1><g2> Save</g2><g3> button & wait.</g3>", ""),
        ("Name:Value", ""),
        ("<g1>our site</g1><g2> has more.</g2>", ""),
        ("today is the date", ""),
        ("Cell", ""),
        ("Confidential", ""),
    ]


def test_unchanged_translations_keep_the_text(report):
    path = report.parent / "fr" / "report.docx"

    translate_file(open_file(path), FakeClient(prefix=""), "fr")

    assert list(parts(path)) == list(PARTS)
    assert [paragraph.message for paragraph in _read(path)[1]] == [
        paragraph.message for paragraph in _read(report)[1]]
    assert parts(path)["word/styles.xml"] == PARTS["word/styles.xml"]


def test_translations_go_into_their_runs(report):
    path = report.parent / "report.fr.docx"
    client = ScriptedClient([{
        "0": "Installation",
        "1": "<g1>Cliquez sur le</g1><g2> bouton Enregistrer</g2><g3> et attendez.</g3>",
        "2": "Nom :Valeur",
        "3": "<g1>notre site</g1><g2> en dit plus.</g2>",
        "4": "aujourd'hui est la date",
        "5": "Cellule",
        "6": "Confidentiel & privé",
    }])

    result = translate_file(open_file(path), client, "fr")

    assert result.translated == 7
    document = parts(path)["word/document.xml"]
    assert ('<w:r w:rsidR="00A1"><w:t xml:space="preserve">Cliquez sur le</w:t></w:r>'
            '<w:r w:rsidR="00B2"><w:t xml:space="preserve"></w:t></w:r>') in document
    assert ('<w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> bouton Enregistrer</w:t></w:r>'
            '<w:r w:rsidR="00D4"><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"></w:t>') in document
    assert '<w:hyperlink r:id="rId5"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>' \
           '<w:t xml:space="preserve">notre site</w:t>' in document
    assert '<w:t xml:space="preserve">Cellule</w:t></w:r><w:r><w:t xml:space="preserve"></w:t></w:r>' in document
    assert parts(path)["word/header1.xml"].endswith(
        '<w:t xml:space="preserve">Confidentiel &amp; privé</w:t></w:r></w:p></w:hdr>')
    assert parts(report) == PARTS


def test_not_a_docx(tmp_path):
    (tmp_path / "report.docx").write_bytes(b"not a zip")

    with pytest.raises(ValueError, match="not a .docx file"):
        open_file(tmp_path / "fr" / "report.docx").untranslated_units()


def test_cli(report, capsys):
    path = report.parent / "de" / "report.docx"

    assert main([str(path), "--provider", "tests.fakes.FakeClient", "--api-key", "k"]) == 0

    assert capsys.readouterr().out == f"{path} (de): translated 7 of 7\n"


def test_the_source_itself_is_left_alone(tmp_path):
    (tmp_path / "en").mkdir()
    path = tmp_path / "en" / "report.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", DOCUMENT)
    before = path.read_bytes()

    result = translate_file(open_file(path, source_language="en"), FakeClient(prefix=""), "en")

    assert (result.untranslated, path.read_bytes()) == (0, before)


def test_a_failed_save_leaves_no_partial_file(report, monkeypatch):
    path = report.parent / "fr" / "report.docx"
    docx_file = open_file(path)
    docx_file.apply(docx_file.untranslated_units()[0].key, "Installation")

    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail)

    with pytest.raises(OSError):
        docx_file.save()
    assert not path.parent.exists() or list(path.parent.iterdir()) == []


@pytest.mark.parametrize("document", [
    '<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<body><p><r><t>Hello world</t></r></p></body></document>',
    '<word:document xmlns:word="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<word:body><word:p><word:r><word:t>Hello world</word:t></word:r></word:p></word:body></word:document>',
])
def test_text_keeps_the_documents_own_element_names(tmp_path, document):
    source = tmp_path / "plain.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", document)
    target = tmp_path / "fr" / "plain.docx"

    translate_file(open_file(target, source_path=source), FakeClient(), "fr")

    saved = parts(target)["word/document.xml"]
    assert "T: Hello world" in saved
    minidom.parseString(saved)


def test_saves_keep_a_symlinked_targets_link_and_mode(report, tmp_path):
    real = tmp_path / "shared.docx"
    real.write_bytes(report.read_bytes())
    real.chmod(0o640)
    (tmp_path / "fr").mkdir()
    link = tmp_path / "fr" / "report.docx"
    link.symlink_to(real)

    translate_file(open_file(link, source_path=report), FakeClient(), "fr")

    assert link.is_symlink() and "T: Install" in parts(real)["word/document.xml"]
    assert real.stat().st_mode & 0o777 == 0o640


def test_a_zip_without_a_word_document_is_refused(tmp_path):
    path = tmp_path / "other.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("hello.txt", "hi")

    with pytest.raises(ValueError, match="other.docx is not a Word document: it has no word/document.xml"):
        open_file(tmp_path / "fr" / "other.docx", source_path=path).untranslated_units()


def test_a_package_naming_a_part_twice_is_refused(tmp_path):
    path = tmp_path / "twice.docx"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("word/document.xml", DOCUMENT)
            package.writestr("word/document.xml", DOCUMENT)

    with pytest.raises(ValueError, match="it has more than one word/document.xml"):
        open_file(tmp_path / "fr" / "twice.docx", source_path=path).untranslated_units()


def test_a_corrupt_part_is_refused_before_translating(tmp_path):
    path = tmp_path / "corrupt.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", DOCUMENT)
        package.writestr("word/media/image1.png", b"png data")
    path.write_bytes(path.read_bytes().replace(b"png data", b"PNG DATA"))

    with pytest.raises(ValueError, match="word/media/image1.png is corrupt"):
        open_file(tmp_path / "fr" / "corrupt.docx", source_path=path).untranslated_units()


@pytest.mark.parametrize("flag_bits, compress_type", [(0x1, zipfile.ZIP_STORED), (0, zipfile.ZIP_LZMA)])
def test_a_package_with_parts_it_cant_copy_is_refused(tmp_path, flag_bits, compress_type):
    path = tmp_path / "odd.docx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", DOCUMENT)
        image = zipfile.ZipInfo("word/media/image1.png")
        image.compress_type = compress_type
        package.writestr(image, b"png")
    if flag_bits:
        # The encrypted flag, in the central directory's entry for the image
        data = bytearray(path.read_bytes())
        entry = data.rindex(b"PK\x01\x02")
        data[entry + 8] |= flag_bits
        path.write_bytes(bytes(data))

    with pytest.raises(ValueError, match="word/media/image1.png is encrypted or compressed"):
        open_file(tmp_path / "fr" / "odd.docx", source_path=path).untranslated_units()


def test_parts_in_utf16_are_written_back_in_utf16(tmp_path):
    source = tmp_path / "wide.docx"
    with zipfile.ZipFile(source, "w") as package:
        wide = DOCUMENT.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
        package.writestr("word/document.xml", wide)
    target = tmp_path / "fr" / "wide.docx"

    translate_file(open_file(target, source_path=source), FakeClient(), "fr")

    saved = zipfile.ZipFile(target).read("word/document.xml")
    assert saved.startswith(codecs.BOM_UTF16_LE) and "T: Install" in saved.decode("utf-16")
    expat.ParserCreate().Parse(saved, True)


def test_text_full_of_entities_takes_linear_time(tmp_path):
    source = tmp_path / "amp.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", DOCUMENT.replace("Install", "&amp;" * 400000))

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "amp.docx", source_path=source).untranslated_units()
    assert time.perf_counter() - started < 2


def test_a_paragraph_whose_text_reads_like_group_tags_is_left_alone(tmp_path):
    document = DOCUMENT.replace("<w:t>the</w:t>", "<w:t>a&lt;/g1&gt;&lt;g2&gt;b</w:t>")
    source = tmp_path / "tags.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", document)

    units = open_file(tmp_path / "fr" / "tags.docx", source_path=source).untranslated_units()

    assert not any("g2&gt;b" in unit.source or "</g1><g2>b" in unit.source for unit in units)
    assert "Install" in [unit.source for unit in units]


def test_a_one_run_paragraph_whose_text_reads_like_a_group_tag_is_left_alone(tmp_path):
    source = tmp_path / "tag.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", f'<w:document {W}><w:body><w:p><w:r><w:t>Type &lt;g1&gt; to start'
                                              "</w:t></w:r></w:p></w:body></w:document>")

    assert open_file(tmp_path / "fr" / "tag.docx", source_path=source).untranslated_units() == []


def test_a_save_takes_linear_time_in_the_number_of_text_runs(tmp_path):
    source = tmp_path / "runs.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", f"<w:document {W}><w:body><w:p><w:r>" + "<w:t>x</w:t>" * 40000
                         + "</w:r></w:p></w:body></w:document>")
    docx_file = open_file(tmp_path / "fr" / "runs.docx", source_path=source)
    [unit] = docx_file.untranslated_units()
    docx_file.apply(unit.key, "y")

    started = time.perf_counter()
    docx_file.save()
    assert time.perf_counter() - started < 1


def test_a_text_element_keeps_the_namespaces_it_declares(tmp_path):
    source = tmp_path / "ns.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", '<a:document xmlns:a="http://schemas.openxmlformats.org/wordprocessingml/'
                         '2006/main"><a:body><a:p><a:r><w:t xmlns:w="http://schemas.openxmlformats.org/'
                         'wordprocessingml/2006/main">Hello</w:t></a:r></a:p></a:body></a:document>')
    target = tmp_path / "fr" / "ns.docx"

    translate_file(open_file(target, source_path=source), FakeClient(), "fr")

    with zipfile.ZipFile(target) as package:
        part = package.read("word/document.xml")
    assert b'<w:t xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xml:space="preserve">' \
           b"T: Hello</w:t>" in part
    expat.ParserCreate(namespace_separator=" ").Parse(part, True)
