import logging
import urllib.error
from io import BytesIO, StringIO
from unittest.mock import patch

import polib
import pytest
from django.core.management import CommandError, call_command

from llm_localize.contrib.django.conf import get_config

PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Hello"
msgstr ""
'''


@pytest.fixture
def locale_dir(tmp_path, settings):
    for lang in ["es", "fr"]:
        path = tmp_path / lang / "LC_MESSAGES" / "django.po"
        path.parent.mkdir(parents=True)
        path.write_text(PO, encoding="utf-8")
    settings.LOCALE_PATHS = [tmp_path]
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FakeClient", "API_KEY": "k"}
    return tmp_path


def msgstr(locale_dir, lang):
    return polib.pofile(str(locale_dir / lang / "LC_MESSAGES" / "django.po")).find("Hello").msgstr


def test_translates_project_po_files(locale_dir):
    call_command("llm_localize", verbosity=0)

    assert msgstr(locale_dir, "es") == msgstr(locale_dir, "fr") == "T: Hello"


def test_the_logger_is_left_as_it_was(locale_dir):
    logger = logging.getLogger("llm_localize")
    before = (logger.handlers[:], logger.level, logger.propagate)

    call_command("llm_localize", verbosity=0)

    # A program calling the command keeps its own logging
    assert (logger.handlers, logger.level, logger.propagate) == before


def test_langs_limits_languages(locale_dir):
    call_command("llm_localize", "--langs", "fr", verbosity=0)

    assert (msgstr(locale_dir, "es"), msgstr(locale_dir, "fr")) == ("", "T: Hello")


def test_explicit_path(locale_dir):
    call_command("llm_localize", str(locale_dir / "es" / "LC_MESSAGES" / "django.po"), verbosity=0)

    assert (msgstr(locale_dir, "es"), msgstr(locale_dir, "fr")) == ("T: Hello", "")


def test_explicit_paths_take_one_language(locale_dir):
    with pytest.raises(CommandError, match="at most one"):
        call_command("llm_localize", "x.po", "--langs", "es", "fr", verbosity=0)


def test_failed_batches_raise(locale_dir, settings):
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FailingClient", "API_KEY": "k"}
    stdout, stderr = StringIO(), StringIO()

    with pytest.raises(CommandError, match="batches failed"):
        call_command("llm_localize", verbosity=0, stdout=stdout, stderr=stderr)

    assert stdout.getvalue() == ""
    assert "1 of 1 batches failed" in stderr.getvalue()
    assert "RuntimeError: boom" in stderr.getvalue()


def test_output_streams(locale_dir):
    stdout, stderr = StringIO(), StringIO()

    call_command("llm_localize", "--langs", "es", stdout=stdout, stderr=stderr)

    assert "1/1 batches done" in stdout.getvalue()
    assert "es/LC_MESSAGES/django.po (es): translated 1 of 1" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_quiet_success_prints_nothing(locale_dir):
    stdout, stderr = StringIO(), StringIO()

    call_command("llm_localize", verbosity=0, stdout=stdout, stderr=stderr)

    assert (stdout.getvalue(), stderr.getvalue()) == ("", "")


def test_fatal_error(locale_dir, settings):
    settings.LLM_LOCALIZE = {"PROVIDER": "openai", "API_KEY": "wrong"}

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, BytesIO(b"invalid key"))

    with (patch("llm_localize.providers.base.urlopen", urlopen),
          pytest.raises(CommandError, match="(?s)invalid key.*Stopped")):
        call_command("llm_localize", verbosity=0)


def test_no_files(tmp_path, settings):
    settings.LOCALE_PATHS = [tmp_path]

    with pytest.raises(CommandError, match="No translation files"):
        call_command("llm_localize", verbosity=0)


def test_config_defaults(settings):
    settings.LLM_LOCALIZE = {}
    settings.LANGUAGE_CODE = "en-us"

    config = get_config()

    assert config["SOURCE_LANGUAGE"] == "en-us"
    assert config["LANGUAGES"] == ["es", "fr"]
    assert config["PROVIDER"] == "openai"


def test_api_key_from_environment(locale_dir, settings, monkeypatch):
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FakeClient"}
    monkeypatch.setenv("FAKE_API_KEY", "from-env")

    call_command("llm_localize", verbosity=0)

    assert msgstr(locale_dir, "es") == "T: Hello"


def test_missing_api_key(locale_dir, settings, monkeypatch):
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FakeClient"}
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_LOCALIZE_API_KEY", raising=False)

    with pytest.raises(CommandError, match="FAKE_API_KEY"):
        call_command("llm_localize", verbosity=0)


def test_fatal_error_still_reports_finished_files(locale_dir, settings):
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FatalOnSecondCallClient", "API_KEY": "k"}
    stdout = StringIO()

    with pytest.raises(CommandError, match="invalid key"):
        call_command("llm_localize", stdout=stdout, stderr=StringIO())

    assert "es/LC_MESSAGES/django.po (es): translated 1 of 1" in stdout.getvalue()
