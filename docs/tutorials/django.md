# Django

This tutorial builds a small Django project from an empty folder and translates it into French and German with llm-localize. Then it translates text your users write, and a file they upload, from background tasks.

You need Python 3, an API key for one of the [providers](../reference/providers.md), and GNU gettext (`brew install gettext` or `apt install gettext`), which Django's `makemessages` and `compilemessages` use. The examples use OpenAI, the default provider.

## 1. Create the project

1. Make a folder and a virtual environment, and install Django with llm-localize:

    ```bash
    mkdir shop-site && cd shop-site
    python -m venv .venv
    source .venv/bin/activate
    pip install "llm-localize[django]"
    ```

2. Create the project and one app:

    ```bash
    django-admin startproject mysite .
    ./manage.py startapp shop
    mkdir -p shop/templates/shop locale
    ```

3. Write a view in `shop/views.py`. It has a plain message, and a plural with a placeholder:

    ```python
    from django.shortcuts import render
    from django.utils.translation import gettext as _, ngettext


    def cart(request):
        count = 3
        context = {
            "title": _("Your cart"),
            "summary": ngettext(
                "You have %(count)d item in your cart.",
                "You have %(count)d items in your cart.",
                count,
            ) % {"count": count},
            "count": count,
            "name": "Sam",
        }
        return render(request, "shop/cart.html", context)
    ```

4. Write its template, `shop/templates/shop/cart.html`, with a template plural and a placeholder:

    ```django
    {% load i18n %}
    <h1>{{ title }}</h1>
    <p>{{ summary }}</p>
    <p>{% blocktranslate count counter=count %}Ships in {{ counter }} day.{% plural %}Ships in {{ counter }} days.{% endblocktranslate %}</p>
    <p>{% blocktranslate %}Welcome back, {{ name }}!{% endblocktranslate %}</p>
    <a href="/checkout/">{% translate "Check out" %}</a>
    ```

5. Route the home page to it in `mysite/urls.py`:

    ```python
    from django.urls import path

    from shop import views

    urlpatterns = [
        path("", views.cart),
    ]
    ```

## 2. Configure i18n

Edit `mysite/settings.py`.

1. Add the app, and llm-localize's Django app:

    ```python
    INSTALLED_APPS = [
        ...,
        "llm_localize.contrib.django",
        "shop",
    ]
    ```

    The app adds the `llm_localize` command and a `--translate` option to `makemessages`. If another installed app also overrides `makemessages`, list `llm_localize.contrib.django` before it.

2. Add `LocaleMiddleware` after `SessionMiddleware`, so Django picks the language from the request:

    ```python
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.locale.LocaleMiddleware",
        "django.middleware.common.CommonMiddleware",
        ...
    ]
    ```

3. List your languages and where the catalogs live:

    ```python
    LANGUAGE_CODE = "en"

    LANGUAGES = [
        ("en", "English"),
        ("fr", "French"),
        ("de", "German"),
    ]

    LOCALE_PATHS = [BASE_DIR / "locale"]
    ```

    llm-localize translates from `LANGUAGE_CODE` into every other language in `LANGUAGES`.

4. Optionally, add an `LLM_LOCALIZE` dict. Every key is optional; this one gives the model some context for every run:

    ```python
    LLM_LOCALIZE = {
        "EXTRA_INSTRUCTIONS": "This is a small online shop. Keep a friendly tone.",
    }
    ```

    The provider, model, batch size and the rest are listed in the [Django reference](../reference/django.md).

## 3. Extract, translate and compile

1. Set your API key. llm-localize reads the provider's usual variable:

    ```bash
    export OPENAI_API_KEY=sk-...
    ```

    To use another provider, set `"PROVIDER"` in `LLM_LOCALIZE` and that provider's variable, e.g. `ANTHROPIC_API_KEY`. See [providers](../reference/providers.md).

2. Extract the messages and translate them in one step:

    ```bash
    ./manage.py makemessages -l fr -l de --translate
    ```

    This runs Django's `makemessages` as usual, then translates what it just wrote. The output ends with one summary line per file (paths trimmed here):

    ```
    processing locale de
    processing locale fr
    ...
    .../locale/fr/LC_MESSAGES/django.po (fr): translated 5 of 5
    .../locale/de/LC_MESSAGES/django.po (de): translated 5 of 5
    ```

    !!! note
        Use `-l` the first time. Django's `makemessages -a` only updates locales that already have a catalog, so in a new project it writes nothing, and `--translate` says so: `No catalog yet for fr, de; start one with makemessages -l fr -l de`. Once `locale/fr` and `locale/de` exist, `-a` works. The same goes for a language you add to `LANGUAGES` later: run `makemessages -l <code> --translate` once for it.

3. Look at `locale/fr/LC_MESSAGES/django.po`. Each `msgstr` is filled in, with the placeholders kept, and the plural has one form per plural form in the file's `Plural-Forms` header (Django's French header has three):

    ```po
    #: shop/templates/shop/cart.html:5
    #, python-format
    msgid "Welcome back, %(name)s!"
    msgstr "Ravi de vous revoir, %(name)s !"

    #: shop/views.py:10
    #, python-format
    msgid "You have %(count)d item in your cart."
    msgid_plural "You have %(count)d items in your cart."
    msgstr[0] "Vous avez %(count)d article dans votre panier."
    msgstr[1] "Vous avez %(count)d articles dans votre panier."
    msgstr[2] "Vous avez %(count)d articles dans votre panier."
    ```

    Translations aren't marked fuzzy, so `compilemessages` uses them. Review them like any other change before you commit.

4. Compile the catalogs:

    ```bash
    ./manage.py compilemessages --ignore .venv
    ```

    `compilemessages` compiles every `locale` directory under the current folder. The `--ignore .venv` keeps it out of a virtual environment inside the project; leave it out if yours lives elsewhere.

5. Start the server and ask for the page in French:

    ```bash
    ./manage.py runserver
    ```

    ```bash
    curl -H "Accept-Language: fr" http://127.0.0.1:8000/
    ```

    ```html
    <h1>Votre panier</h1>
    <p>Vous avez 3 articles dans votre panier.</p>
    <p>Expédition sous 3 jours.</p>
    <p>Ravi de vous revoir, Sam !</p>
    <a href="/checkout/">Passer à la caisse</a>
    ```

    With `Accept-Language: de` you get the German page.

## 4. Rerun as the project changes

1. Add a message to the template:

    ```django
    <p>{% translate "Free returns within 30 days." %}</p>
    ```

2. Extract and translate again. The locale directories exist now, so `-a` works:

    ```bash
    ./manage.py makemessages -a --translate
    ```

    ```
    .../locale/fr/LC_MESSAGES/django.po (fr): translated 1 of 1
    .../locale/de/LC_MESSAGES/django.po (de): translated 1 of 1
    ```

    Only untranslated and fuzzy messages are sent, so this run sent one message per language. Existing translations stay as they are.

3. Run the translation on its own, without extracting. With no arguments, `llm_localize` translates the `django.po` and `djangojs.po` files in `LOCALE_PATHS` for every language in `LANGUAGES` except `LANGUAGE_CODE`:

    ```bash
    ./manage.py llm_localize
    ```

    ```
    .../locale/fr/LC_MESSAGES/django.po (fr): nothing to translate
    .../locale/de/LC_MESSAGES/django.po (de): nothing to translate
    ```

    This is useful after you edit a `.po` file by hand, or after a run where some batches failed.

4. Translate only some languages with `--langs`, and give one-off instructions with `--instructions`. For example, to switch the French cart message to informal "tu", delete its `msgstr` lines' text in `locale/fr/LC_MESSAGES/django.po` (set them to `""`), then:

    ```bash
    ./manage.py llm_localize --langs fr --instructions "Use informal 'tu' in French."
    ```

    ```
    .../locale/fr/LC_MESSAGES/django.po (fr): translated 1 of 1
    ```

    ```po
    msgstr[0] "Tu as %(count)d article dans ton panier."
    ```

    `--instructions` replaces `EXTRA_INSTRUCTIONS` for that run; it doesn't add to it. A changed English message gets a new `msgid` (or is marked fuzzy by `makemessages`), so it's retranslated without this step.

5. Run `compilemessages` again after each change.

If a translation fails a check (a lost placeholder, say), it's left untranslated and counted in the summary as rejected, and the next run tries it again. Run with `-v 2` to see each one. See [output and errors](../reference/output.md).

## 5. Translate user content at runtime

For text your users write, such as product reviews, use `get_translator()`. It builds a `StringTranslator` from your `LLM_LOCALIZE` settings, with the same checks as for `.po` files.

An LLM call takes seconds, so don't make one while handling a request: the user waits, and a worker is tied up. Call it from a background task instead. Here is a Celery task in `shop/tasks.py`:

```python
import logging
from functools import cache

from celery import shared_task
from llm_localize.contrib.django import get_translator

logger = logging.getLogger(__name__)


@cache
def translator():
    # Built on first use: building it needs the API key
    return get_translator(workers=4)


@shared_task
def translate_reviews(texts, language):
    result = translator().translate_with_report(
        texts, language, context="customer reviews in an online shop",
    )
    if not result.complete:
        logger.warning("Some reviews weren't translated: %s %s", result.rejected, result.errors)
    # Fall back to the original text where a translation is missing
    return [t if t is not None else text for t, text in zip(result.translations, texts)]
```

A few things to know:

- Create one translator and reuse it; it's safe to share between threads. Build it lazily, as above: building it without an API key raises an error, so a module-level translator would break every process that imports the module.
- The results come back in the input's order, with `None` for any string that couldn't be translated. Repeated strings are sent once, and blank strings are returned as they are without a call.
- It doesn't cache. Save the results, e.g. on a translation model, if you'll need them again.

To try it without Celery, call the function directly:

```bash
./manage.py shell -c '
from shop.tasks import translate_reviews
print(translate_reviews(["Great kettle, boils in 2 minutes.", "Arrived late but works fine."], "de"))
'
```

```
['Toller Wasserkocher, kocht in 2 Minuten.', 'Kam verspätet an, funktioniert aber einwandfrei.']
```

`StringTranslator` and its options are in the [Python API reference](../reference/python-api.md).

## 6. Translate an uploaded file

`get_file_translator()` builds a `FileTranslator`, which translates a whole file in any supported format: a `.po`, JSON or XLIFF file, a Markdown or Word document, and others. Give it the bytes, the file name (only its extension is used, to pick the format) and the target language.

Add a task to `shop/tasks.py`:

```python
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from llm_localize.contrib.django import get_file_translator


@cache
def file_translator():
    return get_file_translator(max_bytes=1_000_000, max_messages=500)


@shared_task
def translate_document(name, language):
    with default_storage.open(name, "rb") as f:
        result = file_translator().translate(f.read(), name, language)
    if not result.complete:
        logger.warning("%s: %s of %s translated; rejected %s, errors %s", name,
                       result.translated, result.untranslated, result.rejected, result.errors)
    return default_storage.save(f"translations/{language}/{name}", ContentFile(result.content))
```

And a view that stores the upload and queues the task:

```python
from django.core.files.storage import default_storage
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_POST

from shop.tasks import translate_document


@require_POST
def upload(request):
    upload = request.FILES["file"]
    if upload.size > 1_000_000:
        return HttpResponseBadRequest("File too large")
    name = default_storage.save(upload.name, upload)
    translate_document.delay(name, request.POST["language"])
    return JsonResponse({"queued": name}, status=202)
```

Uploads are untrusted, so the translator has limits. It raises `ValueError` before any LLM call for a file over `max_bytes` (default 5 MB), with more than `max_messages` messages to translate (default 2000; each plural form counts), or a ZIP-based file like `.docx` that unpacks to more than `max_unpacked_bytes` (default 50 MB). An invalid file raises `ValueError` too:

```
ValueError: File is 200 bytes; the limit is 100
ValueError: File has 4 messages to translate; the limit is 2
ValueError: x.json is not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```

Django doesn't cap the size of uploaded files itself, so check `upload.size` in the view as well, before you store the file.

For a Markdown file like this one:

```markdown
You can return any item within **30 days**. See [our policy](https://example.com/returns) for details.
```

the French copy keeps the formatting and the link target:

```markdown
Vous pouvez retourner tout article dans un délai de **30 jours**. Consultez [notre politique](https://example.com/returns) pour en savoir plus.
```

A file that holds its own translations, like `.po` or XLIFF, comes back filled in. For a file of one language, like JSON or Markdown, the upload is the source and the result is the new language's file. Messages that couldn't be translated are left untranslated (or missing, for JSON), and `result.complete` is `False`.

## 7. Commit the catalogs

Nothing runs on its own: translations change only when you run one of these commands. Commit the `.po` files with the code that added the messages, and compile them as part of your build or deploy (or commit the `.mo` files too, if you deploy those):

```bash
git add locale/
git commit -m "Translate the cart page"
```

To translate new messages automatically on each push or pull request, see the [CI recipe](../ci.md). For the other ways to run llm-localize, see [getting started](../getting-started.md).
