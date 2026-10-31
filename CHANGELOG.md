# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

- `llm-localize --version` prints the installed version.

## [0.1.0]

First release.

- Translate gettext PO, JSON (i18next, FormatJS, next-intl, vue-i18n), Android `strings.xml`, iOS
  and macOS `.strings` and `.xcstrings`, XLIFF 1.2 and 2.0, Markdown and Word (`.docx`) files.
- OpenAI, Anthropic, Gemini and Grok as providers, and any server that copies their APIs, called
  over plain HTTP with retries, backoff and `Retry-After`.
- Every translation is checked to keep the source's placeholders, HTML tags and attributes, links,
  URLs and ICU arguments, and rejected ones are left for the next run.
- Plural forms from the Unicode CLDR for 224 languages, including gettext `Plural-Forms` headers for
  PO files that lack one.
- The `llm-localize` command, `StringTranslator` and `FileTranslator` for use at runtime, and a
  Django app with an `llm_localize` command and a `makemessages --translate` option.
