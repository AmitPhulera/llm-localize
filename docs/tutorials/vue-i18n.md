# Vue with vue-i18n

This tutorial fills in missing translations in a Vue app that uses [vue-i18n](https://vue-i18n.intlify.dev/), with one JSON file per language:

```
src/locales/en.json   # the source, written by you
src/locales/fr.json   # filled in by llm-localize
src/locales/ru.json
```

vue-i18n's own plural syntax, `car | cars`, doesn't work well with llm-localize for languages like Russian. [Step 6](#6-plurals) explains why and shows what to use instead.

## 1. Install llm-localize

```bash
pipx install llm-localize
# or
uv tool install llm-localize
```

You can also run it without installing: `uvx llm-localize ...`.

## 2. Set an API key

The default provider is OpenAI:

```bash
export OPENAI_API_KEY=sk-...
```

For other providers, see [Providers](../reference/providers.md).

## 3. The source file

`src/locales/en.json`:

```json
{
  "nav": {
    "home": "Home",
    "settings": "Settings"
  },
  "greeting": "Hello, {name}!",
  "contact": "Write to us at support{'@'}example.com",
  "brand": "Acme",
  "footer": "© 2026 @:brand",
  "files_one": "{count} file",
  "files_other": "{count} files"
}
```

It uses named interpolation (`{name}`), a literal (`{'@'}`, since `@` is special in vue-i18n), a linked message (`@:brand`), and a plural written as two keys, `files_one` and `files_other`.

## 4. Translate

```bash
llm-localize src/locales/fr.json src/locales/ru.json
```

```
Translating src/locales/fr.json to fr
src/locales/fr.json: 1/1 batches done, 7/7 translated
Translating src/locales/ru.json to ru
src/locales/ru.json: 1/1 batches done, 7/7 translated
src/locales/fr.json (fr): translated 7 of 7
src/locales/ru.json (ru): translated 7 of 7
```

The language comes from the file name (`fr` in `fr.json`), and the source is the same path with `en`: `src/locales/en.json`. The target files are created if they don't exist.

## 5. The result

`src/locales/ru.json`:

```json
{
  "nav": {
    "home": "Главная",
    "settings": "Настройки"
  },
  "greeting": "Здравствуйте, {name}!",
  "contact": "Напишите нам: support{'@'}example.com",
  "brand": "Acme",
  "footer": "© 2026 @:brand",
  "files_one": "{count} файл",
  "files_few": "{count} файла",
  "files_many": "{count} файлов",
  "files_other": "{count} файла"
}
```

`{name}`, `{count}` and `{'@'}` are checked: a translation that changes or drops one is rejected. `@:brand` was kept, but linked messages aren't checked, so review them. The plural got the four keys Russian needs.

## 6. Plurals

### Why not `car | cars`

vue-i18n's usual plural syntax puts every form in one string, split by `|`. llm-localize sees such a string as ordinary text. It doesn't know it is a plural, so the translation keeps the English number of forms. For this source:

```json
{
  "apple": "no apples | one apple | {count} apples",
  "files": "{n} file | {n} files"
}
```

the Russian translation came back as:

```json
{
  "apple": "нет яблок | одно яблоко | {count} яблок",
  "files": "{n} файл | {n} файлов"
}
```

Russian needs three forms for counts above zero (1 файл, 2 файла, 5 файлов), so vue-i18n renders wrong text:

```
2 яблок / 2 файлов      (should be 2 яблока / 2 файла)
21 яблок / 21 файлов    (should be 21 яблоко / 21 файл)
```

vue-i18n's fix for this is a custom `pluralRules` function for Russian, which expects every Russian message to have the same number of forms in a fixed order. llm-localize doesn't check the number of `|` forms or their order, so the translations won't reliably match the function. With the rule from vue-i18n's guide and the translations above, `files` rendered "1 файлов" for 1, and threw `SyntaxError: Unexpected return type in composer` for 2. You can ask for four forms with `--instructions`, but the model then has to guess which form goes where. In our test it put the wrong form in some slots, and nothing caught it.

French has the same problem in a milder form: vue-i18n's default rule picks the plural form for 0, so you get "0 fichiers" where French uses "0 fichier".

vue-i18n doesn't read ICU plurals (`{count, plural, one {…} other {…}}`) either, unless you set up a custom message compiler. Its default compiler fails with `Invalid token in placeholder: 'count,'`.

### What works: a key per plural category

Write each plural as keys with a CLDR category suffix, `files_one` and `files_other`, as in the source above. llm-localize treats these as plurals: it writes the keys each language needs and checks each form. Then pick the key at runtime with the browser's `Intl.PluralRules`:

```js
// src/plural.js
import { useI18n } from "vue-i18n";

export function usePlural() {
  const { t, te, locale } = useI18n();
  return (key, count) => {
    const category = new Intl.PluralRules(locale.value).select(count);
    const name = te(`${key}_${category}`) ? `${key}_${category}` : `${key}_other`;
    return t(name, { count });
  };
}
```

```vue
<script setup>
import { usePlural } from "./plural";
const tp = usePlural();
</script>

<template>
  <p>{{ tp("files", 21) }}</p>
</template>
```

If a form is missing, for example while a translation is pending, `tp` uses the `_other` key, and vue-i18n falls back to `fallbackLocale` if that is missing too.

## 7. Load the translations

```js
// src/i18n.js
import { createI18n } from "vue-i18n";
import en from "./locales/en.json";
import fr from "./locales/fr.json";
import ru from "./locales/ru.json";

export const i18n = createI18n({
  legacy: false,
  locale: "fr",
  fallbackLocale: "en",
  messages: { en, fr, ru },
});
```

```js
// src/main.js
import { createApp } from "vue";
import App from "./App.vue";
import { i18n } from "./i18n";

createApp(App).use(i18n).mount("#app");
```

## 8. Check the output

This Node script loads the files into vue-i18n and renders a few messages, with the same plural helper:

```js
// check.mjs
import fs from "node:fs";
import { createI18n } from "vue-i18n";

const load = (l) => JSON.parse(fs.readFileSync(`src/locales/${l}.json`, "utf8"));
const i18n = createI18n({
  legacy: false,
  locale: "en",
  fallbackLocale: "en",
  messages: { en: load("en"), fr: load("fr"), ru: load("ru") },
});
const { t, te, locale } = i18n.global;

function tp(key, count) {
  const category = new Intl.PluralRules(locale.value).select(count);
  return t(te(`${key}_${category}`) ? `${key}_${category}` : `${key}_other`, { count });
}

for (const l of ["fr", "ru"]) {
  locale.value = l;
  console.log(`--- ${l}`);
  console.log(t("greeting", { name: "Ada" }));
  console.log(t("contact"), "|", t("footer"));
  console.log([0, 1, 2, 5, 21, 1.5].map((n) => tp("files", n)).join(", "));
}
```

```
$ node check.mjs
--- fr
Bonjour, Ada !
Écrivez-nous à support@example.com | © 2026 Acme
0 fichier, 1 fichier, 2 fichiers, 5 fichiers, 21 fichiers, 1.5 fichier
--- ru
Здравствуйте, Ada!
Напишите нам: support@example.com | © 2026 Acme
0 файлов, 1 файл, 2 файла, 5 файлов, 21 файл, 1.5 файла
```

Every count gets the right form in both languages.

## 9. Run it again after changes

Add `"logout": "Log out"` under `nav` in `en.json` and run again. Only the new message is sent:

```
src/locales/en.json (en): nothing to translate
src/locales/fr.json (fr): translated 1 of 1
src/locales/ru.json (ru): translated 1 of 1
```

Messages that failed a check are missing too, so they're retried on the next run. Until then, vue-i18n shows the `fallbackLocale` text.

**Changed source text isn't noticed.** If you edit `greeting` in `en.json`, the old translations stay. Delete the key from `fr.json` and `ru.json` and run again to retranslate it.

## 10. Add an npm script

```json
{
  "scripts": {
    "translate": "llm-localize src/locales/*.json"
  }
}
```

The glob also matches `en.json`, which has nothing missing. For a new language, name its file once: `llm-localize src/locales/de.json`.

## Next steps

- New to llm-localize? See [Getting started](../getting-started.md).
- Run translations in CI: [CI](../ci.md).
- [Formats: JSON](../reference/formats.md#json), [Command line](../reference/command-line.md), [Output](../reference/output.md).
