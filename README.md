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

It runs on its own as a command line tool, or as a Django app. The engine is format-agnostic: it ships with gettext PO, JSON, Android, iOS, XLIFF, Markdown and Word formats (see [Formats](https://llm-localize.readthedocs.io/en/latest/reference/formats/)), and others plug in as small classes (see [Adding a format](https://llm-localize.readthedocs.io/en/latest/reference/extending/#adding-a-format)).

## Install

```bash
pip install llm-localize             # command line tool and Python API
pip install "llm-localize[django]"   # plus the Django app
uv tool install llm-localize         # just the command, in its own environment
```

The only dependency is polib; the `django` extra adds Django. LLM APIs are called over plain HTTP with the standard library, so no provider SDK is needed. Install gettext if you want the `msgfmt` check (`brew install gettext`, `apt install gettext`).

## Quick start

```bash
export OPENAI_API_KEY=...          # or ANTHROPIC_API_KEY, GEMINI_API_KEY, XAI_API_KEY with --provider
llm-localize locale/fr/LC_MESSAGES/messages.po
llm-localize locales/fr.json locales/de.json          # from locales/en.json
./manage.py makemessages -a --translate               # Django, with llm_localize.contrib.django installed
```

## Documentation

The full documentation is at **[llm-localize.readthedocs.io](https://llm-localize.readthedocs.io/en/latest/)**:

- [Getting started](https://llm-localize.readthedocs.io/en/latest/getting-started/)
- Tutorials: [Django](https://llm-localize.readthedocs.io/en/latest/tutorials/django/), [Flask](https://llm-localize.readthedocs.io/en/latest/tutorials/flask/), [React with i18next](https://llm-localize.readthedocs.io/en/latest/tutorials/react-i18next/), [Vue with vue-i18n](https://llm-localize.readthedocs.io/en/latest/tutorials/vue-i18n/), [Next.js with next-intl](https://llm-localize.readthedocs.io/en/latest/tutorials/nextjs-next-intl/), [Angular](https://llm-localize.readthedocs.io/en/latest/tutorials/angular/)
- [Translating in CI](https://llm-localize.readthedocs.io/en/latest/ci/)
- Reference: [command line](https://llm-localize.readthedocs.io/en/latest/reference/command-line/), [formats](https://llm-localize.readthedocs.io/en/latest/reference/formats/), [LLM providers](https://llm-localize.readthedocs.io/en/latest/reference/providers/), [Django](https://llm-localize.readthedocs.io/en/latest/reference/django/), [Python API](https://llm-localize.readthedocs.io/en/latest/reference/python-api/), [output and errors](https://llm-localize.readthedocs.io/en/latest/reference/output/), [extending](https://llm-localize.readthedocs.io/en/latest/reference/extending/)

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

The documentation is built with MkDocs: `uv run --with-requirements docs/requirements.txt mkdocs serve`.

## License

MIT, see [LICENSE](LICENSE). The table of language names from Django is under the BSD 3-Clause license, in [licenses/Django-LICENSE.txt](licenses/Django-LICENSE.txt).
Data from the Unicode CLDR, like plural rules, is under the Unicode License v3, in [licenses/Unicode-LICENSE.txt](licenses/Unicode-LICENSE.txt).
