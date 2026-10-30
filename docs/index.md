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

It runs on its own as a command line tool, or as a Django app. The engine is format-agnostic: it ships with gettext PO, JSON, Android, iOS, XLIFF, Markdown and Word formats (see [Formats](reference/formats.md)), and others plug in as small classes (see [Adding a format](reference/extending.md#adding-a-format)).

## Where to start

- [Getting started](getting-started.md): install it, set an API key, and translate your first file.
- Tutorials, each from an empty project to translated pages:
  [Django](tutorials/django.md), [Flask](tutorials/flask.md),
  [React with i18next](tutorials/react-i18next.md), [Vue with vue-i18n](tutorials/vue-i18n.md),
  [Next.js with next-intl](tutorials/nextjs-next-intl.md) and [Angular](tutorials/angular.md).
- [Translating in CI](ci.md): open a pull request with new translations whenever the source changes.
- Reference: the [command line](reference/command-line.md), [formats](reference/formats.md),
  [LLM providers](reference/providers.md), [Django](reference/django.md), the [Python API](reference/python-api.md),
  [output and errors](reference/output.md), and [how it works and extending it](reference/extending.md).

## Privacy and cost

Your source strings and their context comments are sent to the LLM provider. Only untranslated, fuzzy or broken messages are sent, so a run after the first one costs little.
