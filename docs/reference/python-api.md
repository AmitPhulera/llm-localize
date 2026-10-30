# Python API

## Translating strings

`StringTranslator` translates a list of strings at runtime, such as content your users enter. It uses the same engine as file translation: strings are batched and sent in parallel, and each translation goes through the same checks.

```python
from llm_localize import StringTranslator

translator = StringTranslator(provider="anthropic", api_key="...")

translator.translate(["Hello", "Hi %(name)s", "Hello"], "fr")
# ["Bonjour", "Salut %(name)s", "Bonjour"]

translator.translate(product_names, "de", context="product names in a hardware store")
```

- Results come back in the same order as the input. A string that couldn't be translated comes back as `None`, so you can fall back to the source text, retry later, or show an error.
- Repeated strings are sent once. Blank strings are returned unchanged, without calling the LLM.
- `context` describes the strings, to help the model. `instructions` overrides `EXTRA_INSTRUCTIONS` for one call, and `source_language` overrides `SOURCE_LANGUAGE`.
- `translate_with_report()` returns the translations along with why any are missing: `rejected` reasons and `errors` from failed batches, as in the file summary.
- A `FatalError`, such as a wrong API key, is raised rather than returned as `None`s.

In Django, build it from `LLM_LOCALIZE` with `get_translator()`, which takes keyword overrides:

```python
from llm_localize.contrib.django import get_translator

translator = get_translator(workers=4)
```

`StringTranslator.from_config(config)` does the same from any dict with the keys of `LLM_LOCALIZE`, e.g. one loaded from your own app's settings.

Create one translator and reuse it; it's safe to share between threads. LLM calls take seconds, so call it from a background task (Celery, RQ, a management command) rather than while handling a request. It doesn't cache translations, so store the results if you'll need them again.

## Translating files

`FileTranslator` translates a file's content at runtime, such as a file a user uploads, in any of the [formats](formats.md). It takes the same options as `StringTranslator`.

```python
from llm_localize import FileTranslator

translator = FileTranslator(provider="anthropic", api_key="...")

result = translator.translate(upload.read(), upload.name, "fr")
result.content     # the translated file's bytes
result.complete    # False if some messages couldn't be translated
result.rejected    # why, e.g. Counter({"placeholders": 1})
```

- A file that holds its translations (PO, XLIFF, `.xcstrings`) comes back filled in. For a file of one language (JSON, Android, `.strings`, Markdown, Word), the upload is the source, and the result is the new language's file.
- The format comes from the name's extension, or `format="json"`. Only the extension is used: the content goes in a temporary directory under a fixed name.
- Uploads are untrusted, so files over `max_bytes` (5 MB), with more than `max_messages` (2000) messages to translate (each plural form counts), or ZIP-based files that unpack to more than `max_unpacked_bytes` (50 MB) raise `ValueError` before any LLM call. Set them on the translator.
- In Django, `get_file_translator()` from `llm_localize.contrib.django` builds one from `LLM_LOCALIZE`.

As with strings, call it from a background task: a document can take a minute.

## Translating a file on disk

The command line's flow is available from Python:

```python
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.providers import get_client

result = translate_file(open_file("messages.po"), get_client("openai"), "fr")
print(result.translated, result.failed_batches)
```
