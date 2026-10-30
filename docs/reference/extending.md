# How it works and extending it

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
