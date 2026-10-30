import io
import json
import zipfile

import polib
import pytest

from llm_localize import FileTranslator
from llm_localize.formats.markdown import MarkdownFile
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


def test_returns_the_new_language_for_a_file_of_one_language():
    source = {"home": {"title": "Welcome"}, "items_one": "{{count}} item", "items_other": "{{count}} items"}

    result = translator_with().translate(json.dumps(source), "en.json", "ru")

    assert json.loads(result.content) == {
        "home": {"title": "T: Welcome"},
        "items_one": "T: {{count}} items", "items_few": "T: {{count}} items",
        "items_many": "T: {{count}} items", "items_other": "T: {{count}} items",
    }


def test_nothing_to_translate_still_gives_a_file():
    result = translator_with().translate(b'{"count": 3, "empty": ""}', "en.json", "fr")

    assert (result.content, result.untranslated) == (b'{"count": 3}', 0)


def test_documents():
    result = translator_with().translate("# Hi\n\nSome `code` here.\n", "README.md", "de")

    assert result.content == b"# T: Hi\n\nT: Some `code` here.\n"


def test_docx():
    document = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                "<w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>")
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w") as package:
        package.writestr("word/document.xml", document)

    result = translator_with().translate(upload.getvalue(), "letter.docx", "es")

    with zipfile.ZipFile(io.BytesIO(result.content)) as package:
        assert '<w:t xml:space="preserve">T: Hello</w:t>' in package.read("word/document.xml").decode()


def test_format_overrides_the_name():
    result = translator_with().translate(b'{"a": "Hi"}', "upload", "fr", format="json")

    assert json.loads(result.content) == {"a": "T: Hi"}


def test_only_the_extension_of_the_name_is_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = translator_with().translate(b'{"a": "Hi"}', "../../etc/en.json", "fr")

    assert json.loads(result.content) == {"a": "T: Hi"}
    assert list(tmp_path.iterdir()) == []


def test_report_says_what_failed():
    client = ScriptedClient([{"0": "Salut {nom}", "1": "Ciao"}])

    result = translator_with(client).translate(b'{"a": "Hi {name}", "b": "Bye"}', "en.json", "fr")

    assert json.loads(result.content) == {"b": "Ciao"}
    assert (result.translated, result.complete, dict(result.rejected)) == (1, False, {"placeholders": 1})


def test_unknown_format():
    with pytest.raises(ValueError, match="No translation format registered for notes.txt"):
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


def test_a_translated_file_is_saved_once(monkeypatch):
    saves = []
    original = MarkdownFile.save
    monkeypatch.setattr(MarkdownFile, "save", lambda self: (saves.append(1), original(self))[1])

    result = translator_with().translate("# Hi\n", "README.md", "fr")

    assert (result.content, len(saves)) == (b"# T: Hi\n", 1)
