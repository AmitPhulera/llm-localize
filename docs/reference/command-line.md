# Command line

```bash
export LLM_LOCALIZE_API_KEY=...
llm-localize locale/fr/LC_MESSAGES/messages.po
llm-localize strings.po --lang pt-br --model gpt-4o
```

The target language comes from `--lang`, the PO `Language` header, or the `<locale>/LC_MESSAGES/` directory, in that order. A file whose `Language` header names another language is refused, since its `Plural-Forms` are that language's; a file without one gets `--lang` as its `Language`. A file without a `Plural-Forms` header gets its language's, made from the Unicode CLDR plural rules, so its plural messages can be translated. This works with any project that uses gettext PO files, e.g. Flask-Babel's `translations/<locale>/LC_MESSAGES/messages.po`. Run `llm-localize --help` for every option.
