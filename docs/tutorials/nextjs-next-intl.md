# Next.js with next-intl

This tutorial fills in missing translations in a Next.js app that uses [next-intl](https://next-intl.dev/). next-intl keeps one JSON file per language, with messages in ICU format:

```
messages/en.json   # the source, written by you
messages/fr.json   # filled in by llm-localize
messages/ru.json
```

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

`messages/en.json`, with a namespace per component:

```json
{
  "HomePage": {
    "title": "Hello, {name}!",
    "inbox": "You have {count, plural, =0 {no new messages} one {# new message} other {# new messages}}.",
    "role": "{role, select, admin {You can edit every project.} other {You can edit your own projects.}}",
    "updated": "Last updated {date, date, medium}",
    "help": "Read the <guide>getting started guide</guide>."
  },
  "Nav": {
    "home": "Home",
    "about": "About us"
  }
}
```

## 4. Translate

```bash
llm-localize messages/fr.json messages/ru.json
```

```
Translating messages/fr.json to fr
messages/fr.json: 1/1 batches done, 7/7 translated
Translating messages/ru.json to ru
messages/ru.json: 1/1 batches done, 6/7 translated
messages/fr.json (fr): translated 7 of 7
messages/ru.json (ru): translated 6 of 7
  rejected 1: ICU syntax 1
```

The language comes from the file name, and the source is `messages/en.json`. Here one Russian translation failed the ICU check, so it was not written. Run the same command again, and only that message is sent:

```bash
llm-localize messages/ru.json
```

```
messages/ru.json (ru): translated 1 of 1
```

Add `-v` to see each rejected translation and why. A rejection now and then is normal; it doesn't make the command fail.

## 5. The result

`messages/ru.json`:

```json
{
  "HomePage": {
    "title": "Здравствуйте, {name}!",
    "inbox": "У вас {count, plural, =0 {нет новых сообщений} one {# новое сообщение} few {# новых сообщения} many {# новых сообщений} other {# нового сообщения} }.",
    "role": "{role, select, admin {Вы можете редактировать все проекты.} other {Вы можете редактировать свои проекты.}}",
    "updated": "Последнее обновление: {date, date, medium}",
    "help": "Прочитайте <guide>руководство для начинающих</guide>."
  },
  "Nav": {
    "home": "Главная",
    "about": "О нас"
  }
}
```

Each ICU message is checked before it's written:

- the arguments (`count`, `role`, `date`) and their types stay the same,
- exact cases like `=0` and every `select` case are kept,
- a `plural` has a case for each category of the target language. English uses `one` and `other`; Russian also needs `few` and `many`, and French needs `many`.

Rich text tags like `<guide>` must be kept too. See [Formats: JSON](../reference/formats.md#json).

## 6. Load the messages, with a fallback

next-intl doesn't fall back to another language. A message missing from `ru.json` (one that was rejected, or added to `en.json` since the last run) shows as its key, `HomePage.inbox`, and next-intl reports a `MISSING_MESSAGE` error.

To show the English text instead, merge the English messages under the locale's in `src/i18n/request.ts`. This uses the [deepmerge](https://www.npmjs.com/package/deepmerge) package (`npm install deepmerge`):

```ts
// src/i18n/request.ts
import { getRequestConfig } from "next-intl/server";
import { hasLocale } from "next-intl";
import deepmerge from "deepmerge";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;

  const messages = (await import(`../../messages/${locale}.json`)).default;
  const fallback = (await import(`../../messages/en.json`)).default;

  return { locale, messages: deepmerge(fallback, messages) };
});
```

In a component:

```tsx
import { useTranslations } from "next-intl";
import Link from "next/link";

export default function HomePage() {
  const t = useTranslations("HomePage");
  return (
    <>
      <h1>{t("title", { name: "Ada" })}</h1>
      <p>{t("inbox", { count: 5 })}</p>
      <p>{t.rich("help", { guide: (chunks) => <Link href="/guide">{chunks}</Link> })}</p>
    </>
  );
}
```

## 7. Check the output

next-intl's core is the `use-intl` package, which works in plain Node. This script renders a few messages in both languages:

```js
// check.mjs
import fs from "node:fs";
import { createTranslator } from "use-intl";

const load = (l) => JSON.parse(fs.readFileSync(`messages/${l}.json`, "utf8"));
for (const locale of ["fr", "ru"]) {
  const t = createTranslator({ locale, messages: load(locale), namespace: "HomePage", timeZone: "UTC" });
  console.log(`--- ${locale}`);
  console.log(t("title", { name: "Ada" }));
  for (const count of [0, 1, 2, 5, 21]) console.log(t("inbox", { count }));
  console.log(t("role", { role: "admin" }));
  console.log(t("updated", { date: new Date("2026-10-31") }));
  console.log(t.markup("help", { guide: (chunks) => `<a href="/guide">${chunks}</a>` }));
}
```

```
$ node check.mjs
--- fr
Bonjour, Ada !
Vous avez aucun nouveau message.
Vous avez 1 nouveau message.
Vous avez 2 nouveaux messages.
...
Dernière mise à jour : 31 oct. 2026
Lisez le <a href="/guide">guide de démarrage</a>.
--- ru
Здравствуйте, Ada!
У вас нет новых сообщений.
У вас 1 новое сообщение.
У вас 2 новых сообщения.
У вас 5 новых сообщений.
У вас 21 новое сообщение.
Вы можете редактировать все проекты.
Последнее обновление: 31 окт. 2026 г.
Прочитайте <a href="/guide">руководство для начинающих</a>.
```

With `inbox` deleted from the Russian messages, the same translator prints `HomePage.inbox`; with the English messages merged in as above, it prints `You have 2 new messages.`

## 8. Run it again after changes

Each run sends only the messages a target file lacks, so after adding messages to `en.json`, running again translates just those.

**Changed source text isn't noticed.** If you edit a message in `en.json`, the old translations stay. Delete the key from each target file and run again to retranslate it.

## 9. Add an npm script

```json
{
  "scripts": {
    "translate": "llm-localize messages/*.json"
  }
}
```

The glob also matches `en.json`, which has nothing missing. For a new language, name its file once: `llm-localize messages/de.json`, then add `de` to `routing.locales`.

## Next steps

- New to llm-localize? See [Getting started](../getting-started.md).
- Run translations in CI: [CI](../ci.md).
- [Command line](../reference/command-line.md), [Output](../reference/output.md).
