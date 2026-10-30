# Django

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

## With `makemessages`

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

## `llm_localize`

With no arguments, `llm_localize` translates `<locale>/LC_MESSAGES/{django,djangojs}.po` under every path in `LOCALE_PATHS`, for every language in `LANGUAGES` except `LANGUAGE_CODE`. Useful options:

```bash
./manage.py llm_localize --langs fr de               # only some languages
./manage.py llm_localize path/to/messages.po         # specific files
./manage.py llm_localize --cleanup-only              # only blank broken translations
./manage.py llm_localize --instructions "Use informal 'tu' in French."
```

## Settings

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
