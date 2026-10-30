import time
import warnings
import zipfile

import pytest

from llm_localize.engine import translate_file
from llm_localize.formats import open_file

from .fakes import FakeClient

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
    units = open_file(report.parent / "fr" / "report.docx", source_path=report).untranslated_units()

    assert [(unit.source, unit.context) for unit in units] == [
        ("Install", ""),
        ("<g1>Click the</g1><g2> Save</g2><g3> button & wait.</g3>", ""),
        ("Name:Value", ""),
        ("<g1>our site</g1><g2> has more.</g2>", ""),
        ("today is the date", ""),
        ("Cell", ""),
        ("Confidential", ""),
    ]


def test_not_a_docx(tmp_path):
    (tmp_path / "report.docx").write_bytes(b"not a zip")

    with pytest.raises(ValueError, match="not a .docx file"):
        open_file(tmp_path / "fr" / "report.docx", source_path=tmp_path / "report.docx").untranslated_units()


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
    docx_file = open_file(path, source_path=report)
    docx_file.apply(docx_file.untranslated_units()[0].key, "Installation")

    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail)

    with pytest.raises(OSError):
        docx_file.save()
    assert not path.parent.exists() or list(path.parent.iterdir()) == []


def test_saves_keep_a_symlinked_targets_link_and_mode(report, tmp_path):
    real = tmp_path / "shared.docx"
    real.write_bytes(report.read_bytes())
    real.chmod(0o640)
    (tmp_path / "fr").mkdir()
    link = tmp_path / "fr" / "report.docx"
    link.symlink_to(real)

    open_file(link, source_path=report).save()

    assert link.is_symlink()
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


def test_text_full_of_entities_takes_linear_time(tmp_path):
    source = tmp_path / "amp.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", DOCUMENT.replace("Install", "&amp;" * 400000))

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "amp.docx", source_path=source).untranslated_units()
    assert time.perf_counter() - started < 2
