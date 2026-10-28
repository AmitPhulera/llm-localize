import subprocess
from unittest.mock import patch

import polib
import pytest

from llm_localize.formats.po.cleanup import (
    clear_translations_at_lines,
    entry_has_control_chars,
    extract_errored_line_numbers,
    remove_errored_translations,
    run_msgfmt,
)


@pytest.fixture
def po_path(tmp_path):
    def write(content):
        path = tmp_path / "django.po"
        path.write_text(content, encoding="utf-8")
        return str(path)
    return write


def test_extract_errored_line_numbers():
    error_output = (
        "dummy.po:10: some error message\n"
        "dummy.po:15: warning: some warning message\n"
        "dummy.po:20: another error message\n"
        "dummy.po:25: yet another error message :with a reason\n"
    )

    assert extract_errored_line_numbers(error_output) == {
        10: "some error message",
        20: "another error message",
        25: "yet another error message :with a reason",
    }


def test_extract_errored_line_numbers_skips_lines_without_line_number():
    error_output = (
        "django.po: warning: Charset missing in header.\n"
        "django.po:42: a format specification for argument 'count' doesn't exist in 'msgstr[1]'\n"
    )

    assert list(extract_errored_line_numbers(error_output)) == [42]


def test_extract_errored_line_numbers_ignores_non_po_lines():
    error_output = (
        "thread 'tokio-rt-worker' panicked at /Users/x/.cargo/registry/src/tokio-1.50.0/"
        "src/runtime/io/driver.rs:196:23:\n"
        "unexpected error when polling the I/O driver: Os { code: 9 }\n"
        "locale/fra/LC_MESSAGES/django.po:32940: 'msgid' and 'msgstr' entries do not both end with '\\n'\n"
    )

    assert list(extract_errored_line_numbers(error_output)) == [32940]


def test_run_msgfmt_returns_result(po_path):
    path = po_path('msgid "Hello"\nmsgstr "Hola"\n')
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="fake error output")

    with patch("subprocess.run", return_value=completed):
        assert run_msgfmt(path).stderr == "fake error output"


def test_run_msgfmt_untranslated(po_path):
    with patch("subprocess.run") as run:
        run_msgfmt(po_path)

    assert run.call_args.kwargs["env"]["LC_ALL"] == "C"


def test_clear_translations_at_lines(po_path):
    path = po_path('msgid "A"\nmsgstr "a"\n\nmsgid "B"\nmsgstr "b"\n\nmsgid "C"\nmsgstr "c"\n')

    # msgstr lines of B and C, plus a second error inside C
    count = clear_translations_at_lines(path, {5: "error at B", 8: "error at C", 9: "again C"})

    assert count == 2
    assert [entry.msgstr for entry in polib.pofile(path)] == ["a", "", ""]


def test_remove_errored_translations_clears_plural_forms(po_path):
    path = po_path(
        'msgid ""\n'
        'msgstr ""\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n'
        '#, python-brace-format\n'
        'msgid "{count} domain membership"\n'
        'msgid_plural "{count} domain memberships"\n'
        'msgstr[0] "Actualizar Membresia de Ubicacion"\n'
        'msgstr[1] "Actualizar Membresia de Ubicacion"\n'
    )
    assert extract_errored_line_numbers(run_msgfmt(path).stderr), "file should be uncompilable before cleanup"

    assert remove_errored_translations(path) == 1

    entry = polib.pofile(path).find("{count} domain membership")
    assert entry.msgstr_plural == {0: "", 1: ""}
    assert not extract_errored_line_numbers(run_msgfmt(path).stderr)


def test_remove_errored_translations_clears_control_chars(po_path):
    path = po_path(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n > 1);\\n"\n\n'
        'msgid "Save — now"\n'
        'msgstr "Enregistrer \x14 maintenant"\n\n'
        'msgid "Cancel — later"\n'
        'msgstr "Annuler — plus tard"\n\n'
        'msgid "{count} page — done"\n'
        'msgid_plural "{count} pages — done"\n'
        'msgstr[0] "{count} page \x14 termin\u00e9e"\n'
        'msgstr[1] "{count} pages — termin\u00e9es"\n'
    )
    assert not extract_errored_line_numbers(run_msgfmt(path).stderr), "msgfmt alone misses control characters"

    assert remove_errored_translations(path) == 2

    updated = polib.pofile(path)
    assert updated.find("Save — now").msgstr == ""
    assert updated.find("Cancel — later").msgstr == "Annuler — plus tard"
    assert updated.find("{count} page — done").msgstr_plural == {0: "", 1: ""}


def test_remove_errored_translations_without_msgfmt(po_path):
    path = po_path('msgid "Save — now"\nmsgstr "Guardar \x14 ahora"\n')

    with patch("shutil.which", return_value=None), patch("subprocess.run") as run:
        assert remove_errored_translations(path) == 1

    run.assert_not_called()


@pytest.mark.parametrize("entry, expected", [
    (polib.POEntry(msgid="Save \u2014 now", msgstr="Guardar \x14 ahora"), True),
    (polib.POEntry(msgid="Save \u2014 now", msgstr="Guardar \u2014 ahora"), False),
    (polib.POEntry(msgid="Page\x0cbreak", msgstr="Salto\x0cde p\u00e1gina"), False),
    (polib.POEntry(
        msgid="{count} invitation", msgid_plural="{count} invitations",
        msgstr_plural={0: "{count} invitaci\u00f3n", 1: "{count} invitaciones"},
    ), False),
    # One broken plural form is enough
    (polib.POEntry(
        msgid="{count} invitation", msgid_plural="{count} invitations",
        msgstr_plural={0: "{count} invitaci\x13n", 1: "{count} invitaciones"},
    ), True),
    # The source of a plural form is both msgid and msgid_plural
    (polib.POEntry(
        msgid="{count} page", msgid_plural="{count}\x0cpages",
        msgstr_plural={0: "{count} p\u00e1gina", 1: "{count}\x0cp\u00e1ginas"},
    ), False),
])
def test_entry_has_control_chars(entry, expected):
    assert entry_has_control_chars(entry) is expected


UTF8_HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'


def test_extract_errored_line_numbers_skips_continuations():
    output = "x.po:8: duplicate message definition...\nx.po:6: ...this is the location of the first definition"

    assert extract_errored_line_numbers(output) == {8: "duplicate message definition..."}


def test_duplicate_messages_are_reported_not_blanked(po_path):
    path = po_path(UTF8_HEADER + 'msgid "Hi"\nmsgstr "Hola"\n\nmsgid "Hi"\nmsgstr "Salut"\n')

    with pytest.raises(ValueError, match="more than once.*msguniq"):
        remove_errored_translations(path)

    assert [entry.msgstr for entry in polib.pofile(path)] == ["Hola", "Salut"]


def test_errors_without_a_line_raise(po_path):
    path = po_path(UTF8_HEADER + 'msgid "Hi"\nmsgstr "Hola"\n')
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="x.po: header broken")

    with patch("subprocess.run", return_value=completed), pytest.raises(ValueError, match="header broken"):
        remove_errored_translations(path)
