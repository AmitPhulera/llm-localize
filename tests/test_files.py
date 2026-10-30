import polib
import pytest

from llm_localize import FileTranslator
from llm_localize.providers.base import FatalError

from .fakes import ScriptedClient

PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Language: fr\\n"

msgid "Hello"
msgstr ""

msgid "Bye"
msgstr "Au revoir"
'''


def translator_with(client=None, **kwargs):
    translator = FileTranslator(provider="tests.fakes.FakeClient", api_key="k", **kwargs)
    if client:
        translator.client = client
    return translator


def test_fills_in_a_file_that_holds_its_translations():
    result = translator_with().translate(PO.encode(), "messages.po", "fr")

    po = polib.pofile(result.content.decode())
    assert (po.find("Hello").msgstr, po.find("Bye").msgstr) == ("T: Hello", "Au revoir")
    assert (result.untranslated, result.translated, result.complete) == (1, 1, True)


def test_unknown_format():
    with pytest.raises(ValueError, match="No translation format"):
        translator_with().translate(b"x", "notes.txt", "fr")


def test_fatal_errors_raise():
    client = ScriptedClient([FatalError("HTTP 401: invalid key", status=401)])

    with pytest.raises(FatalError):
        translator_with(client).translate(PO, "messages.po", "fr")


def test_from_config():
    translator = FileTranslator.from_config({"PROVIDER": "tests.fakes.FakeClient", "API_KEY": "k"}, max_messages=5)

    assert (translator.max_messages, translator.client.api_key) == (5, "k")


def test_absurd_plural_counts_are_refused():
    po = PO.replace('"Language: fr\\n"', '"Language: fr\\n"\n"Plural-Forms: nplurals=10000; plural=0;\\n"') + (
        '\nmsgid "a file"\nmsgid_plural "files"\nmsgstr[0] ""\n')

    with pytest.raises(ValueError, match="no language has 10000 plural forms"):
        translator_with().translate(po, "messages.po", "fr")


def test_translations_msgfmt_clears_make_the_file_incomplete():
    po = PO.split("\nmsgid", 1)[0] + '\nmsgid "Hello\\n"\nmsgstr ""\n'

    # Without the source's trailing newline, msgfmt rejects the translation and cleanup blanks it
    result = translator_with(ScriptedClient([{"0": "Bonjour"}])).translate(po, "fr.po", "fr")

    assert (result.translated, result.cleared, result.complete) == (1, 1, False)
    assert 'msgstr ""' in result.content.decode()
