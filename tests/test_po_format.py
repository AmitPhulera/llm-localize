import polib
import pytest

from llm_localize.formats.po import PoFile

from .test_plurals import ENGLISH_PLURAL_FORMS


def po_header(plural_forms, language=""):
    return (
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        + (f'"Language: {language}\\n"\n' if language else "")
        + f'"Plural-Forms: {plural_forms}\\n"\n'
    )


@pytest.fixture
def write_po(tmp_path):
    def write(content, relative_path="django.po"):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
    return write


class TestUntranslatedUnits:

    def test_selects_empty_fuzzy_and_corrupted(self, write_po):
        po_file = PoFile(write_po(po_header(ENGLISH_PLURAL_FORMS) + """
msgid "Empty"
msgstr ""

msgid "Translated"
msgstr "Traducido"

#, fuzzy
msgid "Fuzzy"
msgstr "Difuso"

msgid "Save \u2014 now"
msgstr "Guardar \x14 ahora"

#~ msgid "Obsolete"
#~ msgstr ""
"""))

        assert [unit.source for unit in po_file.untranslated_units()] == ["Empty", "Fuzzy", "Save \u2014 now"]

    def test_context_includes_msgctxt_and_comments(self, write_po):
        po_file = PoFile(write_po(po_header(ENGLISH_PLURAL_FORMS) + """
#. Month name
msgctxt "month"
msgid "May"
msgstr ""
"""))

        assert po_file.untranslated_units()[0].context == "month\nMonth name"


class TestLanguage:

    def test_from_header(self, write_po):
        assert PoFile(write_po(po_header(ENGLISH_PLURAL_FORMS, language="pt_BR"))).language == "pt_BR"

    def test_from_locale_directory(self, write_po):
        path = write_po(po_header(ENGLISH_PLURAL_FORMS), "locale/fr/LC_MESSAGES/django.po")

        assert PoFile(path).language == "fr"

    def test_unknown(self, write_po):
        assert PoFile(write_po(po_header(ENGLISH_PLURAL_FORMS))).language is None


class TestSave:
    ASCII_PO = (
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=ASCII\\n"\n'
        '\n'
        'msgid "Hello"\n'
        'msgstr ""\n'
        '\n'
        'msgid "Bye"\n'
        'msgstr "Adieu"\n'
    )

    def test_failed_save_leaves_the_file_alone(self, write_po, monkeypatch):
        path = write_po(self.ASCII_PO)
        po_file = PoFile(path)
        po_file.apply(po_file.untranslated_units()[0].key, "Hola")

        def save_halfway(po, fpath=None):
            with open(fpath or po.fpath, "w") as f:
                f.write("msgid")
            raise UnicodeEncodeError("ascii", "ô", 0, 1, "can't encode")

        monkeypatch.setattr(polib.POFile, "save", save_halfway)

        with pytest.raises(UnicodeEncodeError):
            po_file.save()

        assert path.read_text() == self.ASCII_PO
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_saves_through_symlinks(self, write_po, tmp_path):
        target = write_po(self.ASCII_PO, "real/django.po")
        link = tmp_path / "django.po"
        link.symlink_to(target)
        po_file = PoFile(link)

        po_file.apply(po_file.untranslated_units()[0].key, "Hola")
        po_file.save()

        assert link.is_symlink()
        assert polib.pofile(target).find("Hello").msgstr == "Hola"

    def test_keeps_file_mode(self, write_po):
        path = write_po(self.ASCII_PO)
        path.chmod(0o640)
        po_file = PoFile(path)

        po_file.apply(po_file.untranslated_units()[0].key, "Hola")
        po_file.save()

        assert path.stat().st_mode & 0o777 == 0o640
