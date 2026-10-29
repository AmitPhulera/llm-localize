import polib
import pytest
from django.core.management import CommandError, call_command, get_commands

SOURCE = 'from django.utils.translation import gettext as _\n\n_("Hello")\n'


@pytest.fixture
def project(tmp_path, monkeypatch, settings):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "views.py").write_text(SOURCE)
    (tmp_path / "locale").mkdir()
    settings.LOCALE_PATHS = [str(tmp_path / "locale")]
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FakeClient", "API_KEY": "k", "AFTER_MAKEMESSAGES": True}
    return tmp_path


def msgstr(locale_dir, lang):
    return polib.pofile(str(locale_dir / lang / "LC_MESSAGES" / "django.po")).find("Hello").msgstr


def makemessages(*args, **kwargs):
    call_command("makemessages", *args, verbosity=0, **kwargs)


def test_overrides_django_command():
    assert get_commands()["makemessages"] == "llm_localize.contrib.django"


def test_translates_after_makemessages(project):
    makemessages("-l", "es", "-l", "fr")

    assert msgstr(project / "locale", "es") == msgstr(project / "locale", "fr") == "T: Hello"


def test_uses_configured_languages_with_all(project):
    (project / "locale" / "es").mkdir()

    makemessages("--all")

    assert msgstr(project / "locale", "es") == "T: Hello"


def test_locale_names_with_suffixes(project):
    makemessages("-l", "nl_NL-x-informal")

    assert msgstr(project / "locale", "nl_NL-x-informal") == "T: Hello"


def test_app_locale_dirs(project):
    app = project / "myapp"
    (app / "locale").mkdir(parents=True)
    (app / "models.py").write_text(SOURCE)

    makemessages("-l", "es")

    assert msgstr(app / "locale", "es") == "T: Hello"


def test_no_translate_flag(project):
    makemessages("-l", "es", "--no-translate")

    assert msgstr(project / "locale", "es") == ""


def test_off_by_default_and_flag_turns_it_on(project, settings):
    settings.LLM_LOCALIZE = {"PROVIDER": "tests.fakes.FakeClient", "API_KEY": "k"}

    makemessages("-l", "es")
    assert msgstr(project / "locale", "es") == ""

    makemessages("-l", "es", "--translate")
    assert msgstr(project / "locale", "es") == "T: Hello"


def test_translation_errors_fail_the_command_after_writing_catalogs(project, settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.LLM_LOCALIZE = {}

    with pytest.raises(CommandError, match="OPENAI_API_KEY"):
        makemessages("-l", "es", "--translate")

    assert msgstr(project / "locale", "es") == ""
