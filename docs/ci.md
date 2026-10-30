# Translating in CI

Run llm-localize in CI whenever your source strings change, and get the new translations as a pull request
to review, rather than committed straight to your main branch.

## GitHub Actions

1. Add your provider's key as a repository secret: **Settings → Secrets and variables → Actions → New
   repository secret**, named e.g. `OPENAI_API_KEY`.
2. Let workflows open pull requests: **Settings → Actions → General → Workflow permissions**, tick **Allow
   GitHub Actions to create and approve pull requests**.
3. Add `.github/workflows/translate.yml`, with your own paths:

```yaml
name: Translate

on:
  push:
    branches: [main]
    paths: ["locales/en.json"]       # the source file(s): run only when they change
  workflow_dispatch:                 # and by hand, from the Actions tab

permissions:
  contents: write
  pull-requests: write

jobs:
  translate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6

      - name: Translate
        run: uvx llm-localize locales/fr.json locales/de.json locales/es.json
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      # Also after a partly failed run: every finished batch is already saved
      - uses: peter-evans/create-pull-request@v7
        if: ${{ !cancelled() }}
        with:
          branch: translations
          commit-message: Update translations
          title: Update translations
          body: New translations from llm-localize. Review them before merging.
```

Each run sends only the messages still missing, so it costs little after the first. While the pull request
is open, later runs update the same branch.

### PO files

For gettext PO files, install gettext before translating, so each file is checked with `msgfmt --check`:

```yaml
      - run: sudo apt-get install -y gettext
      - run: uvx llm-localize locale/*/LC_MESSAGES/django.po
```

### Django

With the Django app installed, extract and translate in one step, using your project's own environment:

```yaml
      - run: sudo apt-get install -y gettext
      - run: uv sync
      - run: uv run python manage.py makemessages -a --translate
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## Other CI systems

Any CI that can run a command works the same way: install the tool (`pipx install llm-localize` or
`uvx llm-localize`), set the key as a secret environment variable, run it on your files, then commit the
changes to a branch and open a merge request.

## Things to know

- **Exit code.** The command fails when a batch of messages couldn't be translated, such as after repeated
  rate limits, so the job shows red. Rejected translations don't fail it: they stay missing and are retried
  on the next run.
- **Changed source text.** A message whose source text changed isn't translated again, since a JSON or
  Android file doesn't record what its translation was made from. Delete the translation to have it redone.
  PO files mark such messages fuzzy, and those are retranslated.
- **Review.** The checks catch broken placeholders, tags and links, not a wrong meaning. Have someone who
  reads the language look over the pull request when it matters.
