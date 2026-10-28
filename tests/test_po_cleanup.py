import subprocess
from unittest.mock import patch

import polib
import pytest

from llm_localize.formats.po.cleanup import entry_has_control_chars, run_msgfmt


@pytest.fixture
def po_path(tmp_path):
    def write(content):
        path = tmp_path / "django.po"
        path.write_text(content, encoding="utf-8")
        return str(path)
    return write


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
