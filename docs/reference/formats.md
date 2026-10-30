# Formats

The format is chosen by file extension, or with `--format`.

| Format | Extension | Holds | Plurals |
| --- | --- | --- | --- |
| `po` | `.po` | source and translation, one file per language | `msgstr[N]`, from the `Plural-Forms` header |
| `json` | `.json` | one language per file | i18next keys (`items_one`, `items_other`), or ICU messages |
| `android` | `.xml` | one language per file | `<plurals>` items by CLDR category |
| `strings` | `.strings` | one language per file | none (`.stringsdict` isn't supported) |
| `xcstrings` | `.xcstrings` | every language, one at a time with `--lang` | plural variations by CLDR category |
| `xliff` | `.xlf`, `.xliff` | source and translation, one file per language | ICU messages |
| `markdown` | `.md`, `.markdown` | a translated copy of a document per language | — |
| `docx` | `.docx` | a translated copy of a Word document per language | — |

## One file per language

JSON, Android, `.strings`, Markdown and Word files hold one language each, so the source text comes from another file. Translating `locales/fr.json` reads `locales/en.json` and writes the messages `fr.json` lacks, creating the file if needed:

```bash
llm-localize locales/fr.json locales/de.json        # from locales/en.json
llm-localize locales/fr/common.json                 # from locales/en/common.json
llm-localize messages.fr.json --source-lang en_US   # from messages.en_US.json
llm-localize out.json --lang es --source strings.json
llm-localize --source locales/en.json --lang hindi  # writes locales/hi.json
```

The target language is the language code in the path, from the file name first and then its directories, unless `--lang` gives it, as a code or an English name. The source file is the same path with that code swapped for `--source-lang`, unless `--source` gives it. A glob that also matches the source file is fine: it has nothing missing.

With `--source` and `--lang` but no path, the translation goes beside the source: its language swapped in the path (`locales/en.json` gives `locales/hi.json`, `res/values/strings.xml` gives `res/values-hi/strings.xml`, `Base.lproj` gives `hi.lproj`), or added before the extension when the path has none (`report.docx` gives `report.hi.docx`).

A message counts as missing when its key is absent or its value is empty. A changed source text isn't noticed, since the target file doesn't record what it was translated from: delete the translation to have it retranslated.

## JSON

Keys may nest, and each message is sent with its key (`home.title`) as context. Only values are translated, never keys. Translations are written in the source's key order, with the target file's own extra keys kept at the end, and with the target's indentation (or the source's, for a new file). Numbers and other values that aren't text are copied from the source into a new target file, and an existing one keeps its own.

A message that fails to translate, because its batch failed or its translation was rejected, is left out of the target, and the next run tries it again. Until then the app shows whatever it does for a missing key: i18next and vue-i18n fall back to their fallback language, ngx-translate to its fallback language if one is set, and next-intl shows the key unless you merge in the default locale's messages.

- **Arrays** of strings, like `"weekdays": ["Monday", "Tuesday"]`, are translated element by element (`weekdays[0]`), including objects and arrays inside them, up to 10 levels deep. An array goes into the target only once all its strings are translated, so a failure leaves it missing rather than half translated. An array whose shape differs from the source's, like one with fewer elements because the source gained one, is translated again as a whole, since its elements may no longer line up. The model is told to keep values like file formats, locale codes, identifiers and URLs as they are.

- **i18next plurals** are keys with a CLDR category suffix. The target gets one key per category its language uses: `items_one` and `items_other` in English become `items_one`, `items_few`, `items_many` and `items_other` in Russian.
- **ICU messages** (FormatJS, next-intl) stay one string. The model is told the target language's categories, and the translation is checked as ICU: same arguments and select cases, the source's exact cases like `=0`, and a case for every plural category.
- `{{name}}` interpolations, `$t(...)` references and ICU arguments are kept as they are.
- **vue-i18n**'s pipe plurals, like `car | cars`, aren't read as plurals: such a message is translated as one string, keeping the source's number of forms, which is wrong for languages with more, like Russian. Use plural keys instead; the [Vue tutorial](../tutorials/vue-i18n.md) shows how. Linked messages like `@:brand` aren't checked either.

## Android

```bash
llm-localize app/src/main/res/values-fr/strings.xml          # from res/values/strings.xml
llm-localize app/src/main/res/values-{fr,de,pt-rBR}/strings.xml
```

The language comes from the `values-` directory's qualifiers (`values-fr`, `values-pt-rBR`, `values-b+sr+Latn`), and the source is the `values` directory with the same other qualifiers (`values-fr-land` translates `values-land`).

- `<string>` and `<plurals>` are translated, each with its name and any comment just above it as context. Strings marked `translatable="false"` and references like `@string/app_name` are skipped, and `<string-array>` is left alone.
- The model sees apostrophes and quotes unescaped, and they are escaped again when saved (`\'`, `\"`, a leading `\@`), as are bare `&`. Translations that aren't well-formed XML are rejected. Inline tags like `<b>` and `<xliff:g>` must be kept, and so must escapes like `\n` and `\\`; `<xliff:g>` placeholders may change places.
- New translations are added before `</resources>`, with the file's indentation, and empty elements are filled in place. Everything else in the file stays byte for byte, comments included. A new file gets the source's `<resources>` tag, with its namespaces.

## iOS and macOS

```bash
llm-localize MyApp/fr.lproj/Localizable.strings       # from en.lproj, or Base.lproj
llm-localize MyApp/Localizable.xcstrings --lang fr     # a string catalog, one language per run
```

- **`.strings`** files are translated from the same file in `en.lproj` (with `--source-lang`'s code), or `Base.lproj` if there's none. Each entry is sent with the comment above it, and its key when that differs from the text. New entries are added at the end with their comments, empty values are filled in place, and the file keeps its encoding, UTF-8 or UTF-16.
- **`.xcstrings`** catalogs hold every language, so pass the target with `--lang`. An entry is translated when the language has no value, an empty one, or one in the `new` state, and the translation is marked `translated`. Plural variations get one form per CLDR category of the language. Entries marked `shouldTranslate: false`, and those with device variations or substitutions, are skipped. Set `--source-lang` to the catalog's `sourceLanguage` if it isn't English, since the prompt names it.

## XLIFF

```bash
llm-localize src/locale/messages.fr.xlf      # Angular's extract-i18n output, XLIFF 1.2 or 2.0
```

Each unit holds its source and translation, so like a PO file, one file is one language: `--lang`, or the file's `target-language` (1.2) or `trgLang` (2.0), or else the language code in its name, like `fr` in Angular's `messages.fr.xlf`; `--lang` naming another language than the file declares is refused. A unit is translated when it has no `<target>`, an empty one, or one in the `new` or `needs-translation` (1.2) or `initial` (2.0) state, and the translation's state becomes `translated`. Units marked `translate="no"` are skipped, and notes are sent as context.

- Inline elements like `<x id="INTERPOLATION"/>`, `<ph/>`, `<g>` and `<pc>` must be kept with their attributes, though placeholders may change places as word order needs, and translations that aren't well-formed XML are rejected.
- Angular's ICU plurals and selects are checked with the ICU rules, with a plural case for each category of the target language.
- The file is edited in place: a new `<target>` goes right after its `<source>`, and the rest of the file is kept byte for byte.

## Markdown

```bash
llm-localize docs/fr/guide.md                      # from docs/en/guide.md, or docs/guide.md
llm-localize docs/guide.fr.md                      # from docs/guide.en.md, or docs/guide.md
llm-localize translated/guide.md --lang fr --source docs/guide.md
llm-localize --source report.docx --lang hi        # writes report.hi.docx
```

The target path names the language, as for JSON, and the source is the same path with the source language, or with no language at all.

- The document is split into blocks: headings, paragraphs, list items, blockquotes, table cells, footnotes, and HTML blocks that have text. Each is sent with the headings above it as context. The front matter's `title` and `description` are translated too, and written back as valid YAML.
- Code blocks (including those indented inside list items), the rest of the front matter, link reference definitions and HTML comments are copied as they are. Translating the source file itself, as a glob might, does nothing.
- Each translation must keep its `inline code`, link and image targets, reference labels like `[text][label]` and `[^1]`, shortcut references to defined links, backslash escapes like `\[` and `\<`, and HTML tags, and can't add a link definition, a heading or a code fence. A heading's translation is written on one line. A block that fails keeps its source text in the copy, and is counted as rejected.
- Every run translates the whole document, since a changed source can't be matched to the old copy block by block. The copy is written once, at the end. An existing copy is kept as it is when a batch fails or the run is stopped, so a partly failed run can't put source text back over blocks an earlier run translated.

## Word

```bash
llm-localize fr/report.docx         # a French copy of report.docx (or en/report.docx)
llm-localize report.fr.docx
```

A `.docx` file is a ZIP of XML, read with the standard library. Each paragraph of the body, tables, headers, footers, footnotes and endnotes is one message, with the headings above it as context. Word stores a paragraph as runs of differently formatted text, so a paragraph with several is sent with each run in a tag, `<g1>Click </g1><g2>Save</g2>`, and must come back with the same tags in the same order and no text outside them. Each run then gets its own translated text, so bold, italics and links stay on the right words. Tabs, breaks, images and fields between runs stay where they are.

Only the text inside each run changes; styles, images and everything else are copied exactly. As with Markdown, every run translates the whole document.

Older binary `.doc` files aren't supported. Convert them first, e.g. with `soffice --headless --convert-to docx report.doc`.
