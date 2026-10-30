# Flask

This tutorial builds a small Flask app with Flask-Babel, translates it into French and German with
llm-localize, and then translates user content and uploaded files at runtime.

Flask-Babel uses gettext PO files, so the `llm-localize` command works on them directly. You need Python
3.10 or newer, an API key for an LLM provider, and gettext for the `msgfmt --check` step (`brew install
gettext` or `apt install gettext`).

## 1. Set up the project

```bash
mkdir corner-shop && cd corner-shop
python -m venv .venv && source .venv/bin/activate
pip install flask flask-babel llm-localize
```

## 2. Write the app

`app.py` picks the language from a `?lang=` parameter, or else from the browser's `Accept-Language`
header. It has one message with a `%(name)s` placeholder and one plural:

```python
from flask import Flask, render_template, request
from flask_babel import Babel, gettext as _, ngettext

LANGUAGES = ["en", "fr", "de"]


def get_locale():
    lang = request.args.get("lang")
    if lang in LANGUAGES:
        return lang
    return request.accept_languages.best_match(LANGUAGES)


app = Flask(__name__)
babel = Babel(app, locale_selector=get_locale)


@app.route("/")
def index():
    name = request.args.get("name", "Ada")
    count = int(request.args.get("count", 3))
    return render_template(
        "index.html",
        greeting=_("Hello, %(name)s!", name=name),
        cart=ngettext("You have %(num)d item in your cart.",
                      "You have %(num)d items in your cart.", count),
    )
```

`templates/index.html` uses `_()` too:

```html
<!doctype html>
<title>{{ _("Corner Shop") }}</title>
<h1>{{ greeting }}</h1>
<p>{{ cart }}</p>
<p>{{ _("Free delivery on orders over 30 euros.") }}</p>
```

## 3. Extract the messages

1. Tell Babel where to look, in `babel.cfg`:

    ```ini
    [python: **.py]
    [jinja2: **/templates/**.html]
    ```

2. Extract the messages into a template:

    ```bash
    pybabel extract -F babel.cfg -o messages.pot .
    ```

3. Create a catalog for each language:

    ```bash
    pybabel init -i messages.pot -d translations -l fr
    pybabel init -i messages.pot -d translations -l de
    ```

You now have `translations/fr/LC_MESSAGES/messages.po` and `translations/de/LC_MESSAGES/messages.po`,
with every `msgstr` empty.

## 4. Translate with llm-localize

1. Set the key for your provider. OpenAI is the default:

    ```bash
    export OPENAI_API_KEY=sk-...
    ```

    For another provider, see [LLM providers](../reference/providers.md).

2. Translate both catalogs. The language comes from each file's `Language` header, which `pybabel init`
   set, or from the `<locale>/LC_MESSAGES/` directory:

    ```bash
    llm-localize translations/*/LC_MESSAGES/messages.po
    ```

    ```
    Translating translations/de/LC_MESSAGES/messages.po to de
    translations/de/LC_MESSAGES/messages.po: 1/1 batches done, 4/4 translated
    No msgfmt errors in translations/de/LC_MESSAGES/messages.po
    Translating translations/fr/LC_MESSAGES/messages.po to fr
    translations/fr/LC_MESSAGES/messages.po: 1/1 batches done, 4/4 translated
    No msgfmt errors in translations/fr/LC_MESSAGES/messages.po
    translations/de/LC_MESSAGES/messages.po (de): translated 4 of 4
    translations/fr/LC_MESSAGES/messages.po (fr): translated 4 of 4
    ```

    The last lines are the summary. [Output and errors](../reference/output.md) explains what else it can
    report, like rejected translations.

3. Look at the result. The placeholder is kept, and the plural has one translation per French plural form:

    ```po
    #, python-format
    msgid "Hello, %(name)s!"
    msgstr "Bonjour, %(name)s !"

    #, python-format
    msgid "You have %(num)d item in your cart."
    msgid_plural "You have %(num)d items in your cart."
    msgstr[0] "Vous avez %(num)d article dans votre panier."
    msgstr[1] "Vous avez %(num)d articles dans votre panier."
    ```

    Review the translations like any other change before you commit them.

4. Compile the catalogs:

    ```bash
    pybabel compile -d translations
    ```

5. See the page in French:

    ```bash
    flask --app app run
    ```

    In another terminal:

    ```console
    $ curl -H "Accept-Language: fr" "http://127.0.0.1:5000/?count=2"
    <!doctype html>
    <title>Épicerie du coin</title>
    <h1>Bonjour, Ada !</h1>
    <p>Vous avez 2 articles dans votre panier.</p>
    <p>Livraison gratuite pour toute commande supérieure à 30 euros.</p>
    ```

    `curl "http://127.0.0.1:5000/?lang=de"` shows the German page.

## 5. Update the translations later

When you change the app's text, extract again and update the catalogs. Here the delivery threshold
changes, and a new message has a link:

```html
<p>{{ _("Free delivery on orders over 40 euros.") }}</p>
<p>{{ _("Questions? Write to <a href=\"mailto:help@example.com\">help@example.com</a>.") }}</p>
```

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
```

`pybabel update` keeps the old translation of a changed message and marks it fuzzy, and adds the new
message with an empty `msgstr`:

```po
#, fuzzy
msgid "Free delivery on orders over 40 euros."
msgstr "Livraison gratuite pour toute commande supérieure à 30 euros."
```

Run llm-localize again. It sends only the empty and fuzzy messages, and removes the `fuzzy` flag from
the ones it translates:

```console
$ llm-localize translations/*/LC_MESSAGES/messages.po -q
translations/de/LC_MESSAGES/messages.po (de): translated 2 of 2
translations/fr/LC_MESSAGES/messages.po (fr): translated 2 of 2
```

The link's tag, `href` and email address must come back unchanged, or the translation is rejected. Then
run `pybabel compile -d translations` again. A run with nothing missing makes no LLM call and reports
`nothing to translate`.

Some options worth knowing:

- `--instructions` adds to the prompt, for tone or terminology:
  `--instructions "This is a small neighbourhood shop. Address the customer informally."` Only messages
  sent in that run see it, so existing translations keep their old tone. Pass the same instructions on
  every run.
- `--provider` and `--model` choose the LLM:
  `llm-localize translations/fr/LC_MESSAGES/messages.po --provider anthropic` uses `ANTHROPIC_API_KEY`
  and Anthropic's default model.
- `-v` shows each rejected translation with its source.

See [Command line](../reference/command-line.md) for every option, and
[Formats](../reference/formats.md) for how PO files are handled.

## 6. Translate user content at runtime

Messages in your code go through PO files. Content your users write, like product reviews, doesn't. Use
`StringTranslator` for it.

LLM calls take seconds, so don't translate inside a request. Queue a job instead, with RQ or Celery, and
store the result. Put the translator in the module your worker imports, `tasks.py`, so it's created once
per worker and reused:

```python
import json
from pathlib import Path

from llm_localize import StringTranslator

# Created once, when the worker imports this module. Reads OPENAI_API_KEY.
strings = StringTranslator(instructions="This is a small neighbourhood shop.")

STORE = Path("review_translations.json")  # use your database


def translate_reviews(reviews, language):
    texts = [review["text"] for review in reviews]
    result = strings.translate_with_report(texts, language, context="customer reviews of products")
    stored = json.loads(STORE.read_text()) if STORE.exists() else {}
    for review, translation in zip(reviews, result.translations):
        if translation is not None:
            stored.setdefault(str(review["id"]), {})[language] = translation
    STORE.write_text(json.dumps(stored, ensure_ascii=False, indent=2))
    return result
```

Queue it from a view, here with RQ:

```python
from redis import Redis
from rq import Queue

queue = Queue(connection=Redis())
queue.enqueue("tasks.translate_reviews", reviews, "fr")
```

Passing the function as a string keeps the web process from importing `tasks.py`. Creating a
translator without an API key raises `LLMError`, so only the worker needs the key.

Called with two reviews, the result is:

```python
['Excellent pain, encore chaud à 8 h !',
 'Demandez <b>Marie</b>, elle connaît tout sur le fromage.']
```

A few things to know:

- Results come back in the input's order. A string that failed comes back as `None`; the code above
  skips it, so the page shows the original text and a later job can retry it.
- `result.rejected` and `result.errors` say why any are missing.
- Repeated strings are sent once, and blank ones are returned without an LLM call.
- The translator doesn't cache anything. Store the results, as above.
- A wrong API key raises `FatalError` instead of returning `None`s.

See [Python API](../reference/python-api.md) for every option.

## 7. Translate uploaded files

`FileTranslator` translates a file's bytes in any supported format: a user's JSON file of strings, a PO
file, a Markdown or Word document. Add one to `tasks.py`, with limits that suit you:

```python
from llm_localize import FileTranslator

files = FileTranslator(max_bytes=1_000_000, max_messages=500)


def translate_upload(path, filename, language):
    result = files.translate(Path(path).read_bytes(), filename, language)
    out = Path(path).with_name(f"{Path(path).stem}.{language}{Path(filename).suffix}")
    out.write_bytes(result.content)
    return result
```

The upload endpoint saves the file and queues the job. This is a sketch: add authentication, and tell
the user when the job finishes.

```python
import uuid
from pathlib import Path

from flask import abort, request
from werkzeug.utils import secure_filename

UPLOADS = Path("uploads")
ALLOWED = {".po", ".json", ".xml", ".xlf", ".md", ".docx"}

app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # Flask's own limit, the same as max_bytes


@app.post("/translate")
def translate_file():
    upload = request.files.get("file")
    language = request.form.get("lang")
    if upload is None or language not in {"fr", "de"}:
        abort(400)
    filename = secure_filename(upload.filename or "")
    if Path(filename).suffix.lower() not in ALLOWED:
        abort(400, "Unsupported file type")
    UPLOADS.mkdir(exist_ok=True)
    path = UPLOADS / f"{uuid.uuid4().hex}{Path(filename).suffix}"
    upload.save(path)
    queue.enqueue("tasks.translate_upload", str(path), filename, language)
    return {"status": "queued"}, 202
```

For a file of one language, like `en.json`, the upload is the source and `result.content` is the new
language's file. For a PO or XLIFF file, it's the same file filled in. `result.complete` is `False` when
some messages couldn't be translated.

Uploads are untrusted, so `translate()` raises `ValueError` before any LLM call for a file that is too
big (`max_bytes`, 5 MB by default), has too many messages to translate (`max_messages`, 2000, with each
plural form counted), unpacks to too much (`max_unpacked_bytes`, 50 MB, for `.docx`), or isn't valid in
its format. The messages are safe to show the user:

```
File is 1000001 bytes; the limit is 1000000
File has 3 messages to translate; the limit is 2
bad.json is not valid JSON: Expecting value: line 1 column 12 (char 11)
report.docx is not a .docx file: File is not a zip file
No translation format registered for notes.txt (extension '.txt')
```

Catch it in the job and record the failure:

```python
try:
    result = files.translate(content, filename, language)
except ValueError as e:
    ...  # mark the job failed, with str(e) for the user
```

## 8. Translate in CI

To translate new messages on every change, and get them as a pull request to review, see
[Translating in CI](../ci.md).
