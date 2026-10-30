# Angular i18n

This tutorial fills in missing translations for Angular's built-in i18n (`@angular/localize`). Angular extracts your messages to an XLIFF file, and each language gets a copy of it with `<target>` elements:

```
src/locale/messages.xlf      # written by ng extract-i18n
src/locale/messages.fr.xlf   # translated in place by llm-localize
src/locale/messages.ru.xlf
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

## 3. Mark and extract the messages

Add localization support if your app doesn't have it yet:

```bash
ng add @angular/localize
```

Mark text with `i18n` in templates and `$localize` in code. Custom IDs (`@@homeTitle`) keep the IDs stable when the text changes:

```html
<!-- src/app/app.html -->
<h1 i18n="Page title@@homeTitle">Welcome back, {{ name() }}!</h1>
<p i18n="@@cartCount">{count(), plural, =0 {Your cart is empty} =1 {One item in your cart} other {{{ count() }} items in your cart}}</p>
<p i18n="@@termsLink">Read our <a href="/terms">terms of service</a>.</p>
<button i18n-title="@@checkoutTitle" title="Go to payment" i18n="@@checkoutButton">Check out</button>
```

```ts
// src/app/app.ts
protected readonly status = $localize`:Shown after saving@@savedToast:Your changes were saved.`;
```

Extract them:

```bash
ng extract-i18n --output-path src/locale
```

```
Extraction Complete. (Messages: 6)
```

`src/locale/messages.xlf` now holds the source text. The plural looks like this:

```xml
<trans-unit id="cartCount" datatype="html">
  <source>{VAR_PLURAL, plural, =0 {Your cart is empty} =1 {One item in your cart} other {<x id="INTERPOLATION"/> items in your cart}}</source>
  ...
</trans-unit>
```

## 4. Create the language files

Copy the source file once per language, with the language in the name:

```bash
cp src/locale/messages.xlf src/locale/messages.fr.xlf
cp src/locale/messages.xlf src/locale/messages.ru.xlf
```

The extracted file declares no target language, so llm-localize takes it from the file name: `fr` in
`messages.fr.xlf`. A file that declares one, as `target-language="fr"` on its `<file>` element, uses that
instead, and `--lang` overrides both for a single file.

## 5. Translate

```bash
llm-localize src/locale/messages.fr.xlf src/locale/messages.ru.xlf
```

```
Translating src/locale/messages.fr.xlf to fr
src/locale/messages.fr.xlf: 1/1 batches done, 5/6 translated
src/locale/messages.fr.xlf (fr): translated 5 of 6
  rejected 1: plural forms 1
...
```

The rejected message is the plural. Its source only has `=0`, `=1` and `other`, and the model often copies those cases as they are. llm-localize requires a case for each plural category of the target language, so a French translation also needs `one` and `many`, and it's rejected without them. Run the command again; only the missing message is sent, and it usually passes:

```
src/locale/messages.fr.xlf (fr): translated 1 of 1
```

Add `-v` to see each rejected translation.

## 6. The result

The file is edited in place: each `<target>` goes right after its `<source>`, marked `state="translated"`, and nothing else changes. From `messages.ru.xlf`:

```xml
<source>Welcome back, <x id="INTERPOLATION" equiv-text="{{ name() }}"/>!</source>
<target state="translated">С возвращением, <x id="INTERPOLATION" equiv-text="{{ name() }}"/>!</target>
```

```xml
<target state="translated">{VAR_PLURAL, plural, =0 {Ваша корзина пуста} =1 {Один товар в корзине} one {<x id="INTERPOLATION"/> товар в корзине} few {<x id="INTERPOLATION"/> товара в корзине} many {<x id="INTERPOLATION"/> товаров в корзине} other {<x id="INTERPOLATION"/> товара в корзине}}</target>
```

```xml
<target state="translated">Прочитайте <x id="START_LINK" ctype="x-a" equiv-text="&lt;a href=&quot;/terms&quot;&gt;"/>условия использования<x id="CLOSE_LINK" ctype="x-a" equiv-text="&lt;/a&gt;"/>.</target>
```

Placeholders like `<x id="INTERPOLATION"/>` and `<x id="START_LINK"/>` must be kept with their attributes, though they may move. `<note>` descriptions, like "Page title", are sent to the model as context. See [Formats: XLIFF](../reference/formats.md#xliff).

## 7. Build the app in each language

List the locales in `angular.json`, under your project:

```json
"i18n": {
  "sourceLocale": "en-US",
  "locales": {
    "fr": "src/locale/messages.fr.xlf",
    "ru": "src/locale/messages.ru.xlf"
  }
},
```

and set `"localize": true` in the build options (`architect.build.options`). Then:

```bash
ng build
```

The build writes one copy of the app per locale: `dist/<project>/browser/en-US`, `fr` and `ru`. Angular compiles the translations in, so there is nothing to load at runtime.

## 8. Check the output

Serve `dist/<project>/browser` with any static server and open `/fr/` and `/ru/`. With `count` set to 0, 1, 2, 5 and 21, the Russian build showed:

```
С возвращением, Ada!
Ваша корзина пуста
Один товар в корзине
2 товара в корзине
5 товаров в корзине
21 товар в корзине
Прочитайте условия использования.     (the link is still <a href="/terms">)
[Оформить заказ]  title="Перейти к оплате"
Изменения сохранены.
```

A unit without a `<target>` is built with its English source text.

## 9. Updating after changes

`ng extract-i18n` only rewrites `messages.xlf`. It doesn't add new messages to `messages.fr.xlf`, and copying the file again would lose the translations. The [ng-extract-i18n-merge](https://www.npmjs.com/package/ng-extract-i18n-merge) builder merges them for you:

```bash
ng add ng-extract-i18n-merge
```

It finds the language files and updates `angular.json`, so `ng extract-i18n` then also updates `messages.fr.xlf` and `messages.ru.xlf`. It keeps `target-language`. A new message is added with its English text as a `state="new"` target:

```xml
<trans-unit id="footerHelp" datatype="html">
  <source>Need help? Contact support.</source>
  <target state="new">Need help? Contact support.</target>
</trans-unit>
```

and a message whose English text changed is set back to `state="new"`:

```xml
<source>Go to checkout</source>
<target state="new">Commander</target>
```

llm-localize translates `new` targets, so both are sent on the next run:

```
src/locale/messages.fr.xlf (fr): translated 2 of 2
```

```xml
<target state="translated">Besoin d’aide ? Contactez le service d’assistance.</target>
<target state="translated">Passer à la caisse</target>
```

Without the merge builder, a changed source text isn't noticed: delete its `<target>` to have it retranslated.

## 10. Add an npm script

```json
{
  "scripts": {
    "translate": "ng extract-i18n && llm-localize src/locale/messages.*.xlf"
  }
}
```

The glob `messages.*.xlf` matches the language files but not `messages.xlf`, and each file's language comes from its name.

## Next steps

- New to llm-localize? See [Getting started](../getting-started.md).
- Run translations in CI: [CI](../ci.md).
- [Command line](../reference/command-line.md), [Output](../reference/output.md).
