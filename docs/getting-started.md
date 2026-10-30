# Getting started

This page takes you from installing llm-localize to a translated file in a few minutes.

## 1. Install it

```bash
pip install llm-localize             # the command line tool and Python API
pip install "llm-localize[django]"   # plus the Django app
uv tool install llm-localize         # just the command, in its own environment
pipx install llm-localize            # the same, with pipx
```

It needs Python 3.10 or newer. Its only dependency is polib. For gettext PO files, also install gettext,
so each file is checked with `msgfmt --check` after translating:

```bash
brew install gettext      # macOS
apt install gettext       # Debian, Ubuntu
```

## 2. Choose a provider and set its key

llm-localize calls an LLM provider's API with your own key. Set the key for the provider you use:

| Provider | Key variable | Option |
| --- | --- | --- |
| OpenAI (the default) | `OPENAI_API_KEY` | none |
| Anthropic | `ANTHROPIC_API_KEY` | `--provider anthropic` |
| Google Gemini | `GEMINI_API_KEY` | `--provider gemini` |
| xAI Grok | `XAI_API_KEY` | `--provider grok` |

```bash
export OPENAI_API_KEY=sk-...
```

`LLM_LOCALIZE_API_KEY` works for every provider. A local or self-hosted model, like Ollama, needs no key:
see [LLM providers](reference/providers.md).

## 3. Translate a file

Point it at the file to fill in. For a file that holds both languages, like a PO file, that's the file
itself:

```bash
llm-localize locale/fr/LC_MESSAGES/messages.po
```

For a file of one language, like a JSON file, it's the translation's path; the source comes from the same
path with the source language, English unless `--source-lang` says otherwise:

```bash
llm-localize locales/fr.json locales/de.json          # from locales/en.json
```

Each file gets a summary of what happened:

```text
locales/fr.json (fr): translated 42 of 42
```

Only messages missing from the file are sent, so run it again after adding source strings and it
translates just the new ones. Every translation is checked before it's written: a translation that drops a
placeholder, breaks a tag or adds a link is left out and tried again on the next run. See
[Output and errors](reference/output.md) for what the summary can say.

## 4. Choose a model

Each provider has a default model, chosen to translate well at a fair price. To use another, pass
`--model`, or set `LLM_LOCALIZE_MODEL` (in Django, `"MODEL"` in the `LLM_LOCALIZE` setting):

```bash
llm-localize locales/fr.json --provider anthropic --model claude-opus-5-5
export LLM_LOCALIZE_MODEL=gpt-6-luna
```

Providers retire models from time to time. If the default of the version you have installed is retired,
the run stops with a message like this, and setting `LLM_LOCALIZE_MODEL` (or upgrading llm-localize) gets
it going again:

```text
https://api.openai.com/v1 has no model 'gpt-6-luna', or none this API key can use. Pass one it has with
--model, or set LLM_LOCALIZE_MODEL (MODEL in Django's LLM_LOCALIZE).
```

## 5. Add instructions

Tell the model about your product, tone or terms with `--instructions`:

```bash
llm-localize locales/*.json --instructions "A cooking app. Use informal 'du' in German. Keep 'Pantry' in English."
```

## Next

- Follow a tutorial for your framework: [Django](tutorials/django.md), [Flask](tutorials/flask.md),
  [React with i18next](tutorials/react-i18next.md), [Vue with vue-i18n](tutorials/vue-i18n.md),
  [Next.js with next-intl](tutorials/nextjs-next-intl.md) or [Angular](tutorials/angular.md).
- Translate in CI on every change: [Translating in CI](ci.md).
- Look up every option: [Command line](reference/command-line.md) and [Formats](reference/formats.md).
