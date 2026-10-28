import subprocess
from unittest.mock import patch

import polib
import pytest

from llm_localize.formats.po.cleanup import entry_has_control_chars, extract_errored_line_numbers, run_msgfmt


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


def test_extract_errored_line_numbers_skips_continuations():
    output = "x.po:8: duplicate message definition...\nx.po:6: ...this is the location of the first definition"

    assert extract_errored_line_numbers(output) == {8: "duplicate message definition..."}
