import io
import json
import zipfile

import polib
import pytest

from llm_localize import FileTranslator
from llm_localize.formats.markdown import MarkdownFile
from llm_localize.formats.po import PoFile
from llm_localize.providers.base import FatalError

from .fakes import FakeClient, ScriptedClient

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


@pytest.mark.parametrize("content, options, message", [
    (b"x" * 101, {"max_bytes": 100}, "File is 101 bytes; the limit is 100"),
    (json.dumps({str(n): "Hi" for n in range(3)}).encode(), {"max_messages": 2},
     "File has 3 messages to translate; the limit is 2"),
])
def test_limits(content, options, message):
    client = FakeClient()

    with pytest.raises(ValueError, match=message):
        translator_with(client, **options).translate(content, "en.json", "fr")
    assert client.calls == []


def test_zip_bomb():
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", "0" * 2_000)

    with pytest.raises(ValueError, match="unpacks to 2000 bytes; the limit is 1000"):
        translator_with(max_unpacked_bytes=1000).translate(upload.getvalue(), "big.docx", "fr")


@pytest.mark.parametrize("damage", ["deflate", "version"])
def test_a_corrupt_zip_raises_value_error(damage):
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", "<w:document/>" * 100)
    data = bytearray(upload.getvalue())
    if damage == "deflate":
        start = data.index(b"word/document.xml") + len("word/document.xml")
        data[start:start + 8] = b"\xff" * 8
    else:
        # A ZIP version Python can't read
        central = data.index(b"PK\x01\x02")
        data[central + 6:central + 8] = (99).to_bytes(2, "little")

    with pytest.raises(ValueError, match="not a valid ZIP archive|not a .docx file"):
        translator_with().translate(bytes(data), "report.docx", "fr")


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


def test_plural_forms_count_towards_the_limit():
    po = PO.replace('"Language: fr\\n"', '"Language: fr\\n"\n"Plural-Forms: nplurals=3; plural=(n>1);\\n"') + (
        '\nmsgid "a file"\nmsgid_plural "files"\nmsgstr[0] ""\nmsgstr[1] ""\nmsgstr[2] ""\n')

    with pytest.raises(ValueError, match="File has 4 messages to translate; the limit is 3"):
        translator_with(max_messages=3).translate(po, "messages.po", "fr")


def test_absurd_plural_counts_are_refused():
    po = PO.replace('"Language: fr\\n"', '"Language: fr\\n"\n"Plural-Forms: nplurals=10000; plural=0;\\n"') + (
        '\nmsgid "a file"\nmsgid_plural "files"\nmsgstr[0] ""\n')

    with pytest.raises(ValueError, match="no language has 10000 plural forms"):
        translator_with().translate(po, "messages.po", "fr")


@pytest.mark.parametrize("content, name", [(b'msgid "a"\nmsgstr "b"\nnot po\n', "fr.po"), (b"{nope", "en.json")])
def test_invalid_files_raise_value_error_naming_the_upload(content, name):
    with pytest.raises(ValueError) as error:
        translator_with().translate(content, name, "fr")

    assert name in str(error.value) and "source." not in str(error.value)


@pytest.mark.parametrize("catalog", [
    {"strings": []},
    {"strings": {"a": "Hi"}},
    {"strings": {"a": {"localizations": []}}},
    {"strings": {"a": {"localizations": {"en": {"stringUnit": "Hi"}}}}},
    {"strings": {"a": {"localizations": {"en": {"variations": {"plural": {"one": []}}}}}}},
    {"strings": {"a": {"comment": 3}}},
])
def test_malformed_string_catalogs_raise_value_error(catalog):
    with pytest.raises(ValueError, match="x.xcstrings is not a valid string catalog"):
        translator_with().translate(json.dumps(catalog), "x.xcstrings", "fr")


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


def test_a_file_saved_after_each_batch_is_saved_once(monkeypatch):
    saves = []
    original = PoFile.save
    monkeypatch.setattr(PoFile, "save", lambda self: (saves.append(1), original(self))[1])
    po = PO + '\nmsgid "One"\nmsgstr ""\n\nmsgid "Two"\nmsgstr ""\n'

    translator_with(batch_size=1).translate(po, "messages.po", "fr")

    # Only the finished file is returned, so nothing is gained by writing it after each of the 3 batches
    assert len(saves) == 1


@pytest.mark.parametrize("name, depth", [("en.json", 100000), ("en.json", 3000), ("x.xcstrings", 3000)])
def test_too_deeply_nested_json_raises_value_error(name, depth):
    # 3000 levels parse, but would overflow the code walking the document
    deep = '{"strings": ' * depth + "{}" + "}" * depth

    with pytest.raises(ValueError, match=f"{name} nests objects or arrays more than 100 deep"):
        translator_with().translate(deep, name, "fr")


def test_errors_after_translating_name_the_upload():
    # Two entries for one message: msgfmt rejects the file when cleanup checks it
    po = PO + '\nmsgid "Bye"\nmsgstr "Salut"\n'

    with pytest.raises(ValueError) as error:
        translator_with().translate(po, "messages.po", "fr")

    assert "messages.po defines the same message more than once" in str(error.value)
    assert "source." not in str(error.value)
