# Contributing

Bug reports, fixes and new formats or providers are welcome. For anything bigger than a small fix,
open an issue first so we can agree on the approach.

## Setting up

You need [uv](https://docs.astral.sh/uv/) and gettext's `msgfmt` (`brew install gettext`,
`apt-get install gettext`), which the PO tests use.

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
```

CI also runs the tests without Django installed, to check the core doesn't need it:

```bash
uv pip uninstall django pytest-django && uv run --no-sync pytest -p no:django
uv sync --group dev   # to put them back
```

Tests never call a real LLM: use `tests.fakes.FakeClient`, which prefixes each message, or
`ScriptedClient`, which replies with what you give it.

## Changes

- Add a test for every fix and feature, one that fails without the change.
- Keep commits small and focused, each one passing the tests and ruff on its own.
- Update the README when behaviour changes, and add a line to `CHANGELOG.md` under "Unreleased".
- New formats subclass `TranslationFile` or `MonolingualFile`, and new providers `HttpClient`; see
  "Adding a format" and "Adding a provider" in the README.

## Data files

`src/llm_localize/data/` holds data from the Unicode CLDR: plural categories, ordinal categories,
gettext `Plural-Forms` headers made from the plural rules, and English language names. Their source
and version are described in the docstrings of `plurals.py` and `languages.py`. Change them only by
regenerating them from a newer CLDR release.

## Security issues

Please don't open a public issue; see [SECURITY.md](SECURITY.md).
