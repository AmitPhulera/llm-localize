# React with react-i18next

This tutorial fills in missing translations in a React app that uses [react-i18next](https://react.i18next.com/). The translation files are i18next JSON, one file per language:

```
public/locales/en/translation.json   # the source, written by you
public/locales/fr/translation.json   # filled in by llm-localize
public/locales/ru/translation.json
```

If your files live in `src/locales/<lng>/translation.json` instead, everything below works the same way. Only the paths change.

## 1. Install llm-localize

llm-localize is a Python command line tool. Install it once, in its own environment:

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

To use Anthropic, Gemini or Grok, see [Providers](../reference/providers.md).

## 3. The source file

`public/locales/en/translation.json` has nested keys, an i18next plural, `{{name}}` interpolation, a `<Trans>` string and an array:

```json
{
  "nav": {
    "home": "Home",
    "settings": "Settings"
  },
  "welcome": "Welcome back, {{name}}!",
  "cart": {
    "items_one": "{{count}} item in your cart",
    "items_other": "{{count}} items in your cart",
    "checkout": "Check out"
  },
  "terms": "I agree to the <1>terms of service</1> and the <3>privacy policy</3>.",
  "weekdays": ["Monday", "Tuesday", "Wednesday"]
}
```

## 4. Translate

Name each target file. The language comes from the path (`fr` in `public/locales/fr/translation.json`), and the source is the same path with `en` in its place:

```bash
llm-localize public/locales/fr/translation.json public/locales/ru/translation.json
```

```
Translating public/locales/fr/translation.json to fr
public/locales/fr/translation.json: 1/1 batches done, 9/9 translated
Translating public/locales/ru/translation.json to ru
public/locales/ru/translation.json: 1/1 batches done, 9/9 translated
public/locales/fr/translation.json (fr): translated 9 of 9
public/locales/ru/translation.json (ru): translated 9 of 9
```

The `fr` and `ru` directories don't need to exist yet. The plural counts as one message, so there are 9.

## 5. The result

`public/locales/ru/translation.json`:

```json
{
  "nav": {
    "home": "Главная",
    "settings": "Настройки"
  },
  "welcome": "С возвращением, {{name}}!",
  "cart": {
    "items_one": "{{count}} товар в корзине",
    "items_few": "{{count}} товара в корзине",
    "items_many": "{{count}} товаров в корзине",
    "items_other": "{{count}} товара в корзине",
    "checkout": "Оформить заказ"
  },
  "terms": "Я принимаю <1>условия использования</1> и <3>политику конфиденциальности</3>.",
  "weekdays": [
    "Понедельник",
    "Вторник",
    "Среда"
  ]
}
```

Things to note:

- **Plurals.** English has two plural categories, `one` and `other`. Russian has four, so the file gets `items_one`, `items_few`, `items_many` and `items_other`. French gets `items_one`, `items_many` and `items_other`; `many` is CLDR's form for large round numbers like 1,000,000.
- **Interpolation and tags.** `{{name}}`, `{{count}}` and the numbered tags `<1>` and `<3>` are kept. A translation that drops or renames one is rejected and retried on the next run.
- **Keys and order.** Keys are never translated, and the file follows the source's key order.
- **Formatting.** The file uses the source's indentation. Arrays are written one element per line, even if the source has them on one line. If you run Prettier on your locale files, run it after llm-localize.

See [Formats: JSON](../reference/formats.md#json) for the details.

## 6. Load the translations in React

With [i18next-http-backend](https://github.com/i18next/i18next-http-backend), the default `loadPath` is `/locales/{{lng}}/{{ns}}.json`, which is where Vite and Create React App serve `public/locales/...`:

```js
// src/i18n.js
import i18n from "i18next";
import HttpBackend from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

i18n
  .use(HttpBackend)
  .use(initReactI18next)
  .init({
    lng: "fr",
    fallbackLng: "en",
    interpolation: { escapeValue: false },
  });

export default i18n;
```

In a component:

```jsx
import { Trans, useTranslation } from "react-i18next";

export function Cart({ name, count }) {
  const { t } = useTranslation();
  return (
    <>
      <h1>{t("welcome", { name })}</h1>
      <p>{t("cart.items", { count })}</p>
      <p>
        <Trans i18nKey="terms">
          I agree to the <a href="/terms">terms of service</a> and the <a href="/privacy">privacy policy</a>.
        </Trans>
      </p>
    </>
  );
}
```

In `<Trans>`, `<1>` and `<3>` are the indexes of the two links among the children: the text before the first link is child 0.

## 7. Check the output

This Node script loads the three files into i18next and renders `<Trans>` with `react-dom/server`, so you can check the translations without a browser:

```js
// check.mjs
import fs from "node:fs";
import i18next from "i18next";
import { initReactI18next, Trans } from "react-i18next";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const load = (lng) => JSON.parse(fs.readFileSync(`public/locales/${lng}/translation.json`, "utf8"));
await i18next.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: Object.fromEntries(["en", "fr", "ru"].map((l) => [l, { translation: load(l) }])),
});

const Terms = () =>
  h(Trans, { i18nKey: "terms" },
    "I agree to the ", h("a", { href: "/terms" }, "terms of service"),
    " and the ", h("a", { href: "/privacy" }, "privacy policy"), ".");

for (const lng of ["fr", "ru"]) {
  await i18next.changeLanguage(lng);
  console.log(`--- ${lng}`);
  console.log(i18next.t("welcome", { name: "Ada" }));
  for (const count of [1, 3, 5, 21]) console.log(i18next.t("cart.items", { count }));
  console.log(renderToStaticMarkup(h(Terms)));
}
```

```
$ node check.mjs
--- fr
Bon retour, Ada !
1 article dans votre panier
3 articles dans votre panier
5 articles dans votre panier
21 articles dans votre panier
J’accepte les <a href="/terms">conditions d’utilisation</a> et la <a href="/privacy">politique de confidentialité</a>.
--- ru
С возвращением, Ada!
1 товар в корзине
3 товара в корзине
5 товаров в корзине
21 товар в корзине
Я принимаю <a href="/terms">условия использования</a> и <a href="/privacy">политику конфиденциальности</a>.
```

Each count gets the right Russian form, and the links stay on the right words.

## 8. Run it again after changes

Add a key to the English file, `"logout": "Log out"` under `nav`, and run again. Only the missing key is sent:

```
public/locales/fr/translation.json (fr): translated 1 of 1
public/locales/ru/translation.json (ru): translated 1 of 1
```

A message that failed a check is also missing, so it is retried on the next run. Until then, i18next shows the `fallbackLng` text.

**Changed source text isn't noticed.** The French file doesn't record which English text it was translated from, so if you change `"welcome"` in `en`, the old French stays. To retranslate a message, delete its key from each target file and run again.

## 9. Add an npm script

```json
{
  "scripts": {
    "translate": "llm-localize public/locales/*/translation.json"
  }
}
```

```bash
npm run translate
```

The glob also matches the English file; that's fine, as it has nothing missing (`public/locales/en/translation.json (en): nothing to translate`). A glob only matches files that exist, so for a new language, name its file once: `llm-localize public/locales/de/translation.json`.

## Next steps

- New to llm-localize? Start with [Getting started](../getting-started.md).
- Run translations in CI: see [CI](../ci.md).
- All options: [Command line](../reference/command-line.md). What the summary means: [Output](../reference/output.md).
