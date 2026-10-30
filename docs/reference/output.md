# Output and errors

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

The command exits with an error if any batch failed or the run was stopped, but not for rejections, which are expected now and then. In files of messages (PO, JSON, Android, iOS, XLIFF), every finished batch is saved as it completes, so rerunning only sends what's still missing. Markdown and Word copies are written once at the end of a run, which translates the whole document again.
