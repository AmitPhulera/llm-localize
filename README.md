# llm-localize

Fill in missing translations in your i18n files with an LLM, without breaking them.

LLMs translate well but are careless with the parts of a message that aren't prose. `llm-localize` sends only untranslated messages, then checks each translation before it is written:

- **Placeholders** (`%s`, `%(name)s`, `{name}`, Android's `%1$s`, iOS's `%@`) must match the source exactly. Named and numbered ones may move; unnamed ones (`%s`, `{}`) must stay in order.
- **HTML tags** must keep the same names, order and attributes. Only text attributes (`title`, `alt`, `placeholder`, `aria-label`, `aria-description`, and `value` on an `<input>` button) may change value, and the content of `<script>` and `<style>` must stay as it is. Numbered tags, like react-i18next's `<1>…</1>`, must all be kept, in any order.
- **URLs** (`http`, `https`, `ftp`, `mailto:`, `tel:`, `www.`) and email addresses must be unchanged, and none may be added.
- **Control characters** that the model invented (e.g. `—` corrupted into `\x14`) are rejected.
- **Plurals** are translated once per plural form of the target language. The model is told which numbers each form covers ("used when n is 2, 3, 4, 22, …"), worked out from a PO file's `Plural-Forms` header, or from the Unicode CLDR plural rules for formats that name forms `one`, `few`, `many`, `other`.
- **ICU messages** like `{count, plural, one {# file} other {# files}}` (in JSON and XLIFF) must keep their arguments and select cases, and get a plural case for each category the target language uses.
- **Format checks.** PO files are run through `msgfmt --check` afterwards, and any entry it rejects is blanked. Errors no translation caused, like a message defined twice, stop with an error instead. A PO file without a real charset, or in another one, is saved as UTF-8, so any translation fits.

A translation that fails a check is dropped, so that message stays untranslated and is retried on the next run. Fuzzy entries are retranslated and lose their `fuzzy` flag.

It runs on its own as a command line tool, or as a Django app. The engine is format-agnostic: it ships with gettext PO, JSON, Android, iOS, XLIFF and Markdown formats (see [Formats](#formats)), and others plug in as small classes (see [Adding a format](#adding-a-format)).

## Install

```bash
pip install llm-localize             # command line tool and Python API
pip install "llm-localize[django]"   # plus the Django app
uv tool install llm-localize         # just the command, in its own environment
```

The only dependency is polib; the `django` extra adds Django. LLM APIs are called over plain HTTP with the standard library, so no provider SDK is needed. Install gettext if you want the `msgfmt` check (`brew install gettext`, `apt install gettext`).

## Command line

```bash
export LLM_LOCALIZE_API_KEY=...
llm-localize locale/fr/LC_MESSAGES/messages.po
llm-localize strings.po --lang pt-br --model gpt-4o
```

The target language comes from `--lang`, the PO `Language` header, or the `<locale>/LC_MESSAGES/` directory, in that order. A file whose `Language` header names another language is refused, since its `Plural-Forms` are that language's; a file without one gets `--lang` as its `Language`. A file without a `Plural-Forms` header gets its language's, made from the Unicode CLDR plural rules, so its plural messages can be translated. This works with any project that uses gettext PO files, e.g. Flask-Babel's `translations/<locale>/LC_MESSAGES/messages.po`. Run `llm-localize --help` for every option.

## Formats

The format is chosen by file extension, or with `--format`.

| Format | Extension | Holds | Plurals |
| --- | --- | --- | --- |
| `po` | `.po` | source and translation, one file per language | `msgstr[N]`, from the `Plural-Forms` header |
| `json` | `.json` | one language per file | i18next keys (`items_one`, `items_other`), or ICU messages |
| `android` | `.xml` | one language per file | `<plurals>` items by CLDR category |
| `strings` | `.strings` | one language per file | none (`.stringsdict` isn't supported) |
| `xcstrings` | `.xcstrings` | every language, one at a time with `--lang` | plural variations by CLDR category |
| `xliff` | `.xlf`, `.xliff` | source and translation, one file per language | ICU messages |
| `markdown` | `.md`, `.markdown` | a translated copy of a document per language | — |

### One file per language

JSON, Android, `.strings` and Markdown files hold one language each, so the source text comes from another file. Translating `locales/fr.json` reads `locales/en.json` and writes the messages `fr.json` lacks, creating the file if needed:

```bash
llm-localize locales/fr.json locales/de.json        # from locales/en.json
llm-localize locales/fr/common.json                 # from locales/en/common.json
llm-localize messages.fr.json --source-lang en_US   # from messages.en_US.json
llm-localize out.json --lang es --source strings.json
```

The target language is the language code in the path, from the file name first and then its directories, unless `--lang` gives it. The source file is the same path with that code swapped for `--source-lang`, unless `--source` gives it. A glob that also matches the source file is fine: it has nothing missing.

A message counts as missing when its key is absent or its value is empty. A changed source text isn't noticed, since the target file doesn't record what it was translated from: delete the translation to have it retranslated.

### JSON

Keys may nest, and each message is sent with its key (`home.title`) as context. Only values are translated, never keys. Translations are written in the source's key order, with the target file's own extra keys kept at the end, and with the target's indentation (or the source's, for a new file). Numbers and other values that aren't text are copied from the source into a new target file, and an existing one keeps its own.

A message that fails to translate, because its batch failed or its translation was rejected, is left out of the target, and the next run tries it again. Until then the app shows whatever it does for a missing key: i18next and vue-i18n fall back to their fallback language, ngx-translate to its fallback language if one is set, and next-intl shows the key unless you merge in the default locale's messages.

- **Arrays** of strings, like `"weekdays": ["Monday", "Tuesday"]`, are translated element by element (`weekdays[0]`), including objects and arrays inside them, up to 10 levels deep. An array goes into the target only once all its strings are translated, so a failure leaves it missing rather than half translated. An array whose shape differs from the source's, like one with fewer elements because the source gained one, is translated again as a whole, since its elements may no longer line up. The model is told to keep values like file formats, locale codes, identifiers and URLs as they are.

- **i18next plurals** are keys with a CLDR category suffix. The target gets one key per category its language uses: `items_one` and `items_other` in English become `items_one`, `items_few`, `items_many` and `items_other` in Russian.
- **ICU messages** (FormatJS, next-intl, vue-i18n) stay one string. The model is told the target language's categories, and the translation is checked as ICU: same arguments and select cases, the source's exact cases like `=0`, and a case for every plural category.
- `{{name}}` interpolations, `$t(...)` references and ICU arguments are kept as they are.

### Android

```bash
llm-localize app/src/main/res/values-fr/strings.xml          # from res/values/strings.xml
llm-localize app/src/main/res/values-{fr,de,pt-rBR}/strings.xml
```

The language comes from the `values-` directory's qualifiers (`values-fr`, `values-pt-rBR`, `values-b+sr+Latn`), and the source is the `values` directory with the same other qualifiers (`values-fr-land` translates `values-land`).

- `<string>` and `<plurals>` are translated, each with its name and any comment just above it as context. Strings marked `translatable="false"` and references like `@string/app_name` are skipped, and `<string-array>` is left alone.
- The model sees apostrophes and quotes unescaped, and they are escaped again when saved (`\'`, `\"`, a leading `\@`), as are bare `&`. Translations that aren't well-formed XML are rejected. Inline tags like `<b>` and `<xliff:g>` must be kept, and so must escapes like `\n` and `\\`; `<xliff:g>` placeholders may change places.
- New translations are added before `</resources>`, with the file's indentation, and empty elements are filled in place. Everything else in the file stays byte for byte, comments included. A new file gets the source's `<resources>` tag, with its namespaces.

### iOS and macOS

```bash
llm-localize MyApp/fr.lproj/Localizable.strings       # from en.lproj, or Base.lproj
llm-localize MyApp/Localizable.xcstrings --lang fr     # a string catalog, one language per run
```

- **`.strings`** files are translated from the same file in `en.lproj` (with `--source-lang`'s code), or `Base.lproj` if there's none. Each entry is sent with the comment above it, and its key when that differs from the text. New entries are added at the end with their comments, empty values are filled in place, and the file keeps its encoding, UTF-8 or UTF-16.
- **`.xcstrings`** catalogs hold every language, so pass the target with `--lang`. An entry is translated when the language has no value, an empty one, or one in the `new` state, and the translation is marked `translated`. Plural variations get one form per CLDR category of the language. Entries marked `shouldTranslate: false`, and those with device variations or substitutions, are skipped. Set `--source-lang` to the catalog's `sourceLanguage` if it isn't English, since the prompt names it.

### XLIFF

```bash
llm-localize src/locale/messages.fr.xlf      # Angular's extract-i18n output, XLIFF 1.2 or 2.0
```

Each unit holds its source and translation, so like a PO file, one file is one language: its `target-language` (1.2) or `trgLang` (2.0), or `--lang` for a file that doesn't declare one; `--lang` naming another language is refused. A unit is translated when it has no `<target>`, an empty one, or one in the `new` or `needs-translation` (1.2) or `initial` (2.0) state, and the translation's state becomes `translated`. Units marked `translate="no"` are skipped, and notes are sent as context.

- Inline elements like `<x id="INTERPOLATION"/>`, `<ph/>`, `<g>` and `<pc>` must be kept with their attributes, though placeholders may change places as word order needs, and translations that aren't well-formed XML are rejected.
- Angular's ICU plurals and selects are checked with the ICU rules, with a plural case for each category of the target language.
- The file is edited in place: a new `<target>` goes right after its `<source>`, and the rest of the file is kept byte for byte.

### Markdown

```bash
llm-localize docs/fr/guide.md                      # from docs/en/guide.md, or docs/guide.md
llm-localize docs/guide.fr.md                      # from docs/guide.en.md, or docs/guide.md
llm-localize translated/guide.md --lang fr --source docs/guide.md
```

The target path names the language, as for JSON, and the source is the same path with the source language, or with no language at all.

- The document is split into blocks: headings, paragraphs, list items, and blockquotes. Each is sent with the headings above it as context.
- Code blocks are copied as they are. Translating the source file itself, as a glob might, does nothing.
- A block that fails keeps its source text in the copy, and is counted as rejected.
- Every run translates the whole document, since a changed source can't be matched to the old copy block by block.

## LLM providers

Three API styles are built in, plus a preset for Grok. Each works with the vendor's own API and with any server that copies that API. To use another server, set its base URL with `--api-base`, `"API_BASE"` in settings, or the env var below.

| `PROVIDER`  | API               | Default model       | API key env var     | Base URL env var     | Default base URL                            |
| ----------- | ----------------- | ------------------- | ------------------- | -------------------- | ------------------------------------------- |
| `openai`    | Chat Completions  | `gpt-6-luna`        | `OPENAI_API_KEY`    | `OPENAI_BASE_URL`    | `https://api.openai.com/v1`                 |
| `anthropic` | Messages          | `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `https://api.anthropic.com`                 |
| `gemini`    | `generateContent` | `gemini-3.8-flash`  | `GEMINI_API_KEY`    | `GEMINI_BASE_URL`    | `https://generativelanguage.googleapis.com` |
| `grok`      | Chat Completions  | `grok-4.7`          | `XAI_API_KEY`       | `XAI_BASE_URL`       | `https://api.x.ai/v1`                       |

As each vendor's tooling does, an `openai` or `grok` base URL includes the `/v1` and the others don't.

The model is, in order, `--model`, `"MODEL"` in settings, the `LLM_LOCALIZE_MODEL` environment variable, and then the provider's default from the table. The defaults are the current models when a version is released; when a provider retires one, an older version stops with an error naming the model, and setting `LLM_LOCALIZE_MODEL` once (or upgrading) gets it going again.

The API key is read, in order, from `--api-key`, `"API_KEY"` in settings, the `LLM_LOCALIZE_API_KEY` environment variable (used for every provider), and then the provider's own variable from the table. The provider's own variable is only used for the provider's own API: with a different `--api-base`, pass the key explicitly or set `LLM_LOCALIZE_API_KEY`, so an OpenAI key is never sent to some other server. On a shared machine, prefer the environment variables to `--api-key`, which other users can see in the process list.

The API key is required for the vendor's own API, and optional anywhere else, so local servers work without one:

```bash
# Ollama, vLLM, LM Studio, or any OpenAI-compatible server
llm-localize messages.po --api-base http://localhost:11434/v1 --model qwen3

# A hosted OpenAI-compatible gateway
llm-localize messages.po --api-base https://openrouter.ai/api/v1 --model <model-id> --api-key ...

# Claude, through a company proxy
llm-localize messages.po --provider anthropic --api-base https://llm-proxy.example.com
```

Notes by provider:

- **`openai`** asks for a `json_schema` response. For a server that doesn't support it, set `MODEL_PARAMS = {"response_format": {"type": "json_object"}}`, or `{"response_format": None}` to send none. Requests use `temperature: 0.2`.
- **`anthropic`** sends API version `2026-10-21`, which rejects sampling parameters, so it sends no `temperature`. On Anthropic's own API it also turns on server-side refusal fallbacks (`fallbacks: "default"`), so a request a safety classifier declines is retried on another model. They're a beta feature: if the API stops accepting it, requests go on without it, with a warning. A request that is still declined fails that batch, and the batch is retried on the next run.
- **`gemini`** asks for `application/json` and leaves temperature at the model's default, which Google recommends for Gemini 3 models.
- **`grok`** sends the same requests as `openai`, which xAI's API accepts.

`MODEL_PARAMS` are merged into the request body, with dict values merged one level deep. Use them for anything provider-specific, e.g. `{"output_config": {"effort": "low"}}` for Claude, or `{"generationConfig": {"temperature": 0.2}}` for Gemini.

Rate limits (429), overload (500/502/503/504/529), timeouts and connection failures are retried up to 5 times, waiting as long as the server's `Retry-After` asks (up to 5 minutes), or otherwise 1–2, 2–4, 4–8, 8–16 and 16–32 seconds. A reply that reaches the model's output token limit fails its batch with a message to use a smaller batch size. Authentication, billing, permission and not-found errors (401/402/403/404), such as a wrong API key or model name, stop the run at once, since every request would fail the same way.

## Django

```python
INSTALLED_APPS = [
    ...,
    "llm_localize.contrib.django",
]
```

```bash
export OPENAI_API_KEY=...
./manage.py makemessages -a
./manage.py llm_localize
./manage.py compilemessages
```

Nothing runs on its own: translations change only when you run one of these commands. Commit the updated `.po` files (or the compiled `.mo` files, if you deploy those) like any other change.

### With `makemessages`

To extract and translate in one step, pass `--translate`:

```bash
./manage.py makemessages -a --translate
```

This runs Django's `makemessages` unchanged, then `llm_localize` on exactly what it just updated:

- the locales given with `-l` (minus any `-x`), or with `-a` the languages in `LANGUAGES` that have a catalog; it names the others, which `makemessages -l` starts
- the `--domain` (`django` or `djangojs`)
- every locale directory it wrote to, including `locale/` directories inside apps

The source language is skipped. If translation fails, the command exits with an error, but the extracted catalogs are already written, and rerunning translates what's left.

It's off by default because `makemessages` often runs in pre-commit hooks and CI checks, where paid, network-dependent and non-deterministic output is unwelcome. To always translate, set `"AFTER_MAKEMESSAGES": True` in `LLM_LOCALIZE`; `--no-translate` then skips it for one run.

The app provides `makemessages` by overriding Django's command. Django uses the first installed app that defines a command, so if another app in `INSTALLED_APPS` also overrides `makemessages`, list `llm_localize.contrib.django` before it.

### `llm_localize`

With no arguments, `llm_localize` translates `<locale>/LC_MESSAGES/{django,djangojs}.po` under every path in `LOCALE_PATHS`, for every language in `LANGUAGES` except `LANGUAGE_CODE`. Useful options:

```bash
./manage.py llm_localize --langs fr de               # only some languages
./manage.py llm_localize path/to/messages.po         # specific files
./manage.py llm_localize --cleanup-only              # only blank broken translations
./manage.py llm_localize --instructions "Use informal 'tu' in French."
```

### Settings

Every key is optional:

```python
LLM_LOCALIZE = {
    "PROVIDER": "openai",          # "openai", "anthropic", "gemini", "grok", or a dotted path
    "API_BASE": None,              # None: the provider's API; set for compatible servers
    "MODEL": None,                 # None: LLM_LOCALIZE_MODEL, then the provider's default
    "API_KEY": None,               # None: LLM_LOCALIZE_API_KEY, then e.g. OPENAI_API_KEY
    "MODEL_PARAMS": {},            # extra request params, e.g. {"temperature": 0}
    "SOURCE_LANGUAGE": None,       # None: LANGUAGE_CODE
    "LANGUAGES": None,             # None: LANGUAGES minus the source language
    "LOCALE_PATHS": None,          # None: LOCALE_PATHS, or ./locale
    "DOMAINS": ["django", "djangojs"],
    "FORMAT": None,                # None: detect from the file extension
    "BATCH_SIZE": 50,              # messages per LLM request
    "WORKERS": 10,                 # LLM requests in flight at once
    "EXTRA_INSTRUCTIONS": "",      # e.g. "Use gender-neutral language."
    "AFTER_MAKEMESSAGES": False,   # also run after ./manage.py makemessages
}
```

## Translating strings in your app

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

## Python API

The command line flow is available from Python:

```python
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.providers import get_client

result = translate_file(open_file("messages.po"), get_client("openai"), "fr")
print(result.translated, result.failed_batches)
```

## Output and errors

Each file gets a summary that adds up, listing only what happened:

```
locale/fr/LC_MESSAGES/django.po (fr): translated 112 of 130
  rejected 6: placeholders 4, HTML tags 2
  1 of 3 batches failed:
    HTTP 400 from https://api.openai.com/v1/chat/completions: context length exceeded
  cleared 2 broken translations
```

- **Rejected** translations failed a check, or were missing from the reply. They stay untranslated and are retried on the next run. Use `-v` (CLI) or `-v 2` (Django) to see each one, with its source and the rejected text.
- **Failed batches** got an API error after retries, or a reply that wasn't JSON. Identical errors are listed once, with a count. Use `-v`/`-v 2` for tracebacks.
- **Cleared** translations were already saved but break the file, e.g. `msgfmt --check` errors. They're blanked so the next run retranslates them. If `msgfmt` still rejects the file for another reason, such as a duplicate message (fix it with `msguniq`), the run stops with its errors.

Progress goes to stdout in Django and stderr in the CLI, and warnings and errors always go to stderr. The CLI prints the summary on stdout. Django prints it on stdout, or on stderr when batches failed, and `-v 0` hides it unless something failed.

The command exits with an error if any batch failed or the run was stopped, but not for rejections, which are expected now and then. Every finished batch is saved as it completes, so rerunning only sends what's still missing.

## How it works

1. A `TranslationFile` lists its untranslated messages as `TranslationUnit` objects (source text, optional plural text and forms, optional context).
2. The engine batches the units and sends each batch to the LLM as a flat JSON object. Batches run in parallel threads.
3. The engine parses each reply and validates every translation. It then writes the valid ones back and saves the file, one batch at a time under a lock, so finished work survives an interrupted run.
4. The format's `cleanup()` blanks anything that is still broken. For PO files, that is control characters and `msgfmt --check` errors.

## Adding a format

Subclass `TranslationFile` for a file that holds both the source and the translation, like PO, or `MonolingualFile` (in `llm_localize.formats.monolingual`) for one language per file, like JSON: it finds the source file and the language, and you implement `read_messages(path)`, `apply` and `save`. For a `TranslationFile`:

```python
from llm_localize.formats.base import TranslationFile
from llm_localize.units import TranslationUnit

class JsonFile(TranslationFile):
    name = "json"
    extensions = (".json",)
    instructions = "Messages use ICU MessageFormat."   # added to the prompt

    def untranslated_units(self):
        return [TranslationUnit(key=k, source=v["source"])
                for k, v in self.data.items() if not v.get("translation")]

    def apply(self, key, translation):
        self.data[key]["translation"] = translation

    def save(self):
        ...
```

Use it with `--format myproject.formats.JsonFile`, or `"FORMAT"` in settings. Override `find_problem(source, translation)` to change the checks: it returns a short reason, which is counted in the summary, or `None` if the translation is fine, and `cleanup()` to add a format-specific check after translating.

## Adding a provider

Most LLM servers copy one of the three built-in APIs, so try `--api-base` first. For anything else, subclass `llm_localize.providers.base.HttpClient` and implement `call_llm(system_prompt, user_message)`, which returns the model's text reply. Use `self.post_json(url, payload, headers)` for the request. It raises `TransientError` for responses worth retrying, `FatalError` for ones that stop the run, and `LLMError` (with the API's message) for anything else. For a non-HTTP backend, subclass `LLMClient` instead and raise those errors yourself. Select your class with `--provider myproject.llm.MyClient` or `"PROVIDER"` in settings.

## Privacy and cost

Your source strings and their context comments are sent to the LLM provider. Only untranslated, fuzzy or broken messages are sent, so a run after the first one costs little.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .

# The core without Django, as CI runs it
uv pip uninstall django pytest-django && uv run --no-sync pytest -p no:django
uv sync --group dev   # to put them back
```

## License

MIT, see [LICENSE](LICENSE). The table of language names from Django is under the BSD 3-Clause license, in [licenses/Django-LICENSE.txt](licenses/Django-LICENSE.txt).
Data from the Unicode CLDR, like plural rules, is under the Unicode License v3, in [licenses/Unicode-LICENSE.txt](licenses/Unicode-LICENSE.txt).
