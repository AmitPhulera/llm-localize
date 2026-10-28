import io
import json
import urllib.error
from collections import Counter
from unittest.mock import patch

import polib
import pytest

from llm_localize.cli import main
from llm_localize.engine import FileResult
from llm_localize.runner import summarize

PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Language: es\\n"

msgid "Hello"
msgstr ""
'''


@pytest.fixture
def po_path(tmp_path):
    path = tmp_path / "django.po"
    path.write_text(PO, encoding="utf-8")
    return path


def test_translates(po_path, capsys):
    exit_code = main([str(po_path), "--provider", "tests.fakes.FakeClient", "--api-key", "k"])

    assert exit_code == 0
    assert polib.pofile(str(po_path)).find("Hello").msgstr == "T: Hello"
    out, err = capsys.readouterr()
    assert out == f"{po_path} (es): translated 1 of 1\n"
    assert "1/1 batches done" in err


def test_the_summary_lists_the_commonest_errors():
    errors = Counter({f"HTTP 400: bad request {n}": 1 for n in range(7)})
    errors["HTTP 503: busy"] = 3
    result = FileResult(path="fr.po", language="fr", untranslated=10, translated=0, batches=10, failed_batches=10,
                        errors=errors)

    lines = summarize(result).splitlines()

    assert lines[2] == "    HTTP 503: busy (3 batches)"
    assert lines[-1] == "    and 3 other errors (3 batches)"
    assert len(lines) == 8


def test_quiet_only_prints_summary(po_path, capsys):
    main([str(po_path), "--provider", "tests.fakes.FakeClient", "--api-key", "k", "-q"])

    out, err = capsys.readouterr()
    assert (out, err) == (f"{po_path} (es): translated 1 of 1\n", "")


def test_fatal_error(po_path, capsys):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"invalid key"))

    with patch("llm_localize.providers.base.urlopen", urlopen), pytest.raises(SystemExit) as exit_info:
        main([str(po_path), "--api-key", "wrong"])

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "HTTP 401" in err and "invalid key" in err and "Stopped" in err


def test_compatible_server_without_api_key(po_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        reply = {"choices": [{"message": {"content": json.dumps({"0": "Hola"})}}]}
        return io.BytesIO(json.dumps(reply).encode())

    with patch("llm_localize.providers.base.urlopen", urlopen):
        exit_code = main([str(po_path), "--api-base", "http://localhost:11434/v1", "--model", "llama"])

    assert exit_code == 0
    assert requests[0].full_url == "http://localhost:11434/v1/chat/completions"
    assert polib.pofile(str(po_path)).find("Hello").msgstr == "Hola"


def test_cleanup_only_needs_no_api_key(po_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main([str(po_path), "--cleanup-only"]) == 0
    assert polib.pofile(str(po_path)).find("Hello").msgstr == ""


def test_failed_batches_exit_nonzero(po_path, capsys):
    assert main([str(po_path), "--provider", "tests.fakes.FailingClient", "--api-key", "k"]) == 1

    out, err = capsys.readouterr()
    assert "1 of 1 batches failed:\n    RuntimeError: boom" in out
    assert "batch 1 failed: RuntimeError: boom" in err
    assert "Traceback" not in err


def test_verbose_shows_tracebacks(po_path, capsys):
    main([str(po_path), "--provider", "tests.fakes.FailingClient", "--api-key", "k", "-v"])

    assert "Traceback" in capsys.readouterr().err


def test_missing_api_key_is_a_clean_error(po_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        main([str(po_path)])

    assert exit_info.value.code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_language_required_when_file_has_none(tmp_path, capsys):
    path = tmp_path / "django.po"
    path.write_text('msgid "Hello"\nmsgstr ""\n')

    with pytest.raises(SystemExit):
        main([str(path), "--provider", "tests.fakes.FakeClient", "--api-key", "k"])

    assert "target language" in capsys.readouterr().err


def test_fatal_error_still_reports_finished_files(tmp_path, capsys):
    first, second = tmp_path / "a.po", tmp_path / "b.po"
    first.write_text(PO, encoding="utf-8")
    second.write_text(PO, encoding="utf-8")

    with pytest.raises(SystemExit):
        main([str(first), str(second), "--provider", "tests.fakes.FatalOnSecondCallClient", "--api-key", "k"])

    out, err = capsys.readouterr()
    assert out == f"{first} (es): translated 1 of 1\n"
    assert "invalid key" in err


@pytest.mark.parametrize("option, value", [("--batch-size", "0"), ("--batch-size", "-1"), ("--workers", "0")])
def test_rejects_non_positive_numbers(po_path, capsys, option, value):
    with pytest.raises(SystemExit) as exit_info:
        main([str(po_path), "--provider", "tests.fakes.FakeClient", "--api-key", "k", option, value])

    assert exit_info.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err
    assert polib.pofile(str(po_path)).find("Hello").msgstr == ""


def test_cleanup_only_and_no_cleanup_conflict(po_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([str(po_path), "--cleanup-only", "--no-cleanup"])

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_cleanup_only_without_a_language(tmp_path, capsys):
    path = tmp_path / "messages.po"
    path.write_text('msgid "Hello"\nmsgstr "Hola\x14"\n', encoding="utf-8")

    exit_code = main([str(path), "--cleanup-only"])

    assert exit_code == 0
    assert polib.pofile(str(path)).find("Hello").msgstr == ""
    assert capsys.readouterr().out == f"{path}: nothing to translate\n  cleared 1 broken translations\n"
