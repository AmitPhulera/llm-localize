import logging
import urllib.error
from io import BytesIO
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
