import time

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.markdown import MarkdownFile

from .fakes import FakeClient, ScriptedClient

GUIDE = '''---
title: "Getting started"
description: Install and run the app
layout: docs
---

# Getting started

Welcome to **Acme**. Read the [guide](https://example.com/guide "Guide") or the [FAQ][faq].
This line wraps.

## Install

1. Run `pip install acme`.
2. Open the app
   and sign in.
   - Nested item with [the docs].

> **Note:** keep your key secret.
>
> It's in `~/.acme`.

| Option | Meaning |
| ------ | ------- |
| `--fast` | Skips `checks` |
| `a\\|b` | Pipe |

```bash
acme --help
```

    indented code

<!-- comment
spanning lines -->

<div align="center">
  <img src="logo.png" alt="Logo">
</div>

<p>Some <b>HTML</b> text</p>

Setext heading
--------------

- [ ] Todo item

---

[faq]: https://example.com/faq
[the docs]: https://example.com/docs
'''


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
    return tmp_path / "docs"


def test_unchanged_translations_give_back_the_document(docs):
    path = docs / "fr" / "guide.md"

    translate_file(open_file(path), FakeClient(prefix=""), "fr")

    assert path.read_text(encoding="utf-8") == GUIDE


def test_blocks(docs):
    units = open_file(docs / "fr" / "guide.md").untranslated_units()

    assert [(unit.source, unit.context) for unit in units] == [
        ("Getting started", "Front matter: title"),
        ("Install and run the app", "Front matter: description"),
        ("Getting started", ""),
        ('Welcome to **Acme**. Read the [guide](https://example.com/guide "Guide") or the [FAQ][faq].\n'
         "This line wraps.", "Section: Getting started"),
        ("Install", "Section: Getting started"),
        ("Run `pip install acme`.", "Section: Getting started > Install"),
        ("Open the app\nand sign in.", "Section: Getting started > Install"),
        ("Nested item with [the docs].", "Section: Getting started > Install"),
        ("**Note:** keep your key secret.\n\nIt's in `~/.acme`.", "Section: Getting started > Install"),
        ("Option", "Section: Getting started > Install"),
        ("Meaning", "Section: Getting started > Install"),
        ("`--fast`", "Section: Getting started > Install"),
        ("Skips `checks`", "Section: Getting started > Install"),
        ("`a\\|b`", "Section: Getting started > Install"),
        ("Pipe", "Section: Getting started > Install"),
        ("<p>Some <b>HTML</b> text</p>", "Section: Getting started > Install"),
        ("Setext heading", "Section: Getting started"),
        ("Todo item", "Section: Getting started > Setext heading"),
    ]


def test_translations_keep_the_structure(docs):
    path = docs / "fr" / "guide.md"

    result = translate_file(open_file(path), FakeClient(), "fr")

    assert result.translated == 18
    text = path.read_text(encoding="utf-8")
    assert 'title: "T: Getting started"\n' in text
    assert "layout: docs\n" in text
    assert "2. T: Open the app\n   and sign in.\n   - T: Nested item with [the docs].\n" in text
    assert "> T: **Note:** keep your key secret.\n>\n> It's in `~/.acme`.\n" in text
    assert "| T: `--fast` | T: Skips `checks` |\n" in text
    assert "```bash\nacme --help\n```\n" in text
    assert "T: Setext heading\n--------------\n" in text
    assert "- [ ] T: Todo item\n" in text
    assert text.endswith("[faq]: https://example.com/faq\n[the docs]: https://example.com/docs\n")


@pytest.mark.parametrize("translation, reason", [
    ("Lancez `pip installer acme`.", "inline code"),
    ("Lancez `pip install acme`.", None),
    ("Lisez le [guide](https://example.com/guide-fr) ou la [FAQ][faq].", "links"),
    ("Lisez le [guide](https://example.com/guide) ou la [FAQ][foire].", "links"),
    ("Lisez le [mode d'emploi](https://example.com/guide) ou la [foire aux questions][faq].", None),
    ("Élément avec [la documentation].", "links"),
    ("Élément avec [the docs].", None),
    ("Un <b>gras</b> perdu", "HTML tags"),
])
def test_find_problem(docs, translation, reason):
    markdown_file = open_file(docs / "fr" / "guide.md")
    source = {
        "Lancez": "Run `pip install acme`.",
        "Lisez": "Read the [guide](https://example.com/guide) or the [FAQ][faq].",
        "Élément": "Item with [the docs].",
        "Un": "A <i>bold</i> loss",
    }[translation.split()[0]]

    assert markdown_file.find_problem(source, translation) == reason


@pytest.mark.parametrize("target, source", [
    ("docs/fr/guide.md", "docs/guide.md"),
    ("docs/guide.fr.md", "docs/guide.md"),
    ("docs/fr/guide.md", "docs/en/guide.md"),
])
def test_source_from_path(tmp_path, target, source):
    (tmp_path / source).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / source).write_text("# Hi\n")

    markdown_file = open_file(tmp_path / target, source_language="en")

    assert (markdown_file.language, markdown_file.source_path) == ("fr", str(tmp_path / source))


def test_a_path_without_a_language_needs_a_source(docs):
    with pytest.raises(ValueError, match="pass it with --source"):
        MarkdownFile(docs / "guide.md", language="fr").untranslated_units()


def test_cli(docs, capsys):
    path = docs / "de" / "guide.md"

    assert main([str(path), "--provider", "tests.fakes.FakeClient", "--api-key", "k"]) == 0

    assert capsys.readouterr().out == f"{path} (de): translated 18 of 18\n"


def test_the_source_itself_is_left_alone(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    path = tmp_path / "docs" / "en" / "guide.md"
    path.write_text("# Hello\n")

    result = translate_file(open_file(path, source_language="en"), FakeClient(), "en")

    assert (result.untranslated, path.read_text()) == (0, "# Hello\n")


@pytest.mark.parametrize("line, source, translation, expected", [
    ("title: 'Welcome'", "Welcome", "Bienvenue à l'application", "title: 'Bienvenue à l''application'"),
    ('title: "Welcome"', "Welcome", 'Le "guide"', 'title: "Le \\"guide\\""'),
    ("title: Welcome", "Welcome", "Étapes : installation", 'title: "Étapes : installation"'),
    ("title: Welcome", "Welcome", "Bienvenue", "title: Bienvenue"),
    ("title: 'It''s here'", "It's here", "C'est ici", "title: 'C''est ici'"),
])
def test_front_matter_stays_valid_yaml(tmp_path, line, source, translation, expected):
    (tmp_path / "guide.md").write_text(f"---\n{line}\n---\n")
    path = tmp_path / "fr" / "guide.md"

    units = open_file(path).untranslated_units()
    translate_file(open_file(path), ScriptedClient([{"0": translation}]), "fr")

    assert units[0].source == source
    assert path.read_text().splitlines()[1] == expected


def test_code_inside_a_list_item_is_not_translated(tmp_path):
    (tmp_path / "guide.md").write_text('- Example\n\n      print("Hello")\n\n  More about it.\n')

    units = open_file(tmp_path / "fr" / "guide.md").untranslated_units()

    assert [unit.source for unit in units] == ["Example", "More about it."]


def test_footnotes_are_translated(tmp_path):
    (tmp_path / "guide.md").write_text("Text[^1].\n\n[^1]: The footnote\n    explains things.\n")
    path = tmp_path / "fr" / "guide.md"

    translate_file(open_file(path), FakeClient(), "fr")

    assert path.read_text() == "T: Text[^1].\n\n[^1]: T: The footnote\n    explains things.\n"


def test_label_order_is_explained(docs):
    assert "in the order they come in the source" in open_file(docs / "fr" / "guide.md").instructions


@pytest.mark.parametrize("source, translation, reason", [
    ("Read [guide](docs/a_(b).md)", "Lisez [guide](docs/a_(b).evil)", "links"),
    ("Read [guide](docs/a_(b).md)", "Lisez le [guide](docs/a_(b).md)", None),
    ('Read [guide](https://x.example "Guide")', 'Lisez [guide](https://x.example "Mode d\'emploi")', None),
    ("See [one][a] and [two][b].", "Voir [un][b] et [deux][a].", "links"),
])
def test_links_keep_their_targets(docs, source, translation, reason):
    assert open_file(docs / "fr" / "guide.md").find_problem(source, translation) == reason


def test_table_cells_keep_code_spans_of_several_backticks(tmp_path):
    path = tmp_path / "fr" / "table.md"
    (tmp_path / "table.md").write_text("| a | b |\n|---|---|\n| x | ``y| z`` |\n", encoding="utf-8")

    translate_file(open_file(path, source_path=tmp_path / "table.md"), FakeClient(), "fr")

    assert path.read_text(encoding="utf-8").splitlines()[2] == "| T: x | T: ``y| z`` |"


CODE_IN_CONTAINERS = """1. Install:

    ```bash
    npm install

    npm start
    ```

2. Run it
    ~~~
    ./run
    ~~~

- Item
  ~~~
  y = 2
  ~~~

> Quoted text
> on two lines.
>
> ~~~python
> x = 1
>
> print(x)
> ~~~
>
>     z = 3
>
> More quoted text.
"""


def test_code_in_list_items_and_blockquotes_is_not_translated(tmp_path):
    (tmp_path / "code.md").write_text(CODE_IN_CONTAINERS, encoding="utf-8")
    target = tmp_path / "fr" / "code.md"

    units = open_file(target, source_path=tmp_path / "code.md").untranslated_units()
    translate_file(open_file(target, source_path=tmp_path / "code.md"), FakeClient(), "fr")

    assert [unit.source for unit in units] == [
        "Install:", "Run it", "Item", "Quoted text\non two lines.", "More quoted text."]
    assert target.read_text(encoding="utf-8") == (
        CODE_IN_CONTAINERS.replace("Install:", "T: Install:").replace("Run it", "T: Run it")
        .replace("- Item", "- T: Item").replace("> Quoted text", "> T: Quoted text")
        .replace("> More", "> T: More"))


def test_code_in_containers_round_trips(tmp_path):
    (tmp_path / "code.md").write_text(CODE_IN_CONTAINERS, encoding="utf-8")
    target = tmp_path / "fr" / "code.md"

    translate_file(open_file(target, source_path=tmp_path / "code.md"), FakeClient(prefix=""), "fr")

    assert target.read_text(encoding="utf-8") == CODE_IN_CONTAINERS


def test_translated_table_cells_stay_one_cell(tmp_path):
    (tmp_path / "t.md").write_text("| A | B |\n|---|---|\n| c | `x|y` |\n", encoding="utf-8")
    target = tmp_path / "fr" / "t.md"

    translate_file(open_file(target, source_path=tmp_path / "t.md"),
                   ScriptedClient([{"0": "A", "1": "B", "2": "x | y\nz", "3": "`x|y`"}]), "fr")

    assert target.read_text(encoding="utf-8").splitlines()[2] == r"| x \| y z | `x|y` |"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_only_line_endings_end_lines(tmp_path, newline):
    source = newline.join(["# Title", "", "First line second line,", "next\x0cpage", "- item one",
                           "  goes on", "", "> quoted", "> lines", "", "```", "code\x85here", "```", ""])
    (tmp_path / "s.md").write_text(source, encoding="utf-8", newline="")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_bytes().decode() == source


@pytest.mark.parametrize("source", [
    "---\ntitle: |\n  A title\n  on two lines\ndescription: >-\n  Folded\n---\n\nText.\n",
    "---\ntitle: A long title\n  that goes on\n---\n\nText.\n",
    '---\ntitle: "Line\\nBreak \\t \\"tab\\" \\u00e9"\n---\n\nText.\n',
    "\ufeff---\nlayout: post\ntitle: Guide\n---\n\nText.\n",
    "<div>\r\nHello\r\n</div>\r\n",
    "- first line  \n  second line  \n  third\n\n[^1]: a note  \n    goes on\n",
])
def test_unchanged_translations_keep_the_document(tmp_path, source):
    (tmp_path / "s.md").write_text(source, encoding="utf-8", newline="")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_bytes().decode() == source


@pytest.mark.parametrize("source, messages", [
    ("---\ntitle: |\n  A title\n---\n\nText.\n", ["Text."]),
    ("\ufeff---\nlayout: post\ntitle: Guide\n---\n\nText.\n", ["Guide", "Text."]),
    ('<script>\nvar msg = "hello";\n\nfetch(url);\n</script>\n\n<PRE>\ncode\n</pre>\n\n'
     '<style>p {}</style>\n\nText.\n', ["Text."]),
])
def test_only_text_is_sent(tmp_path, source, messages):
    (tmp_path / "s.md").write_text(source, encoding="utf-8")

    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == messages


def test_a_title_translated_with_a_line_break_stays_one_value(tmp_path):
    (tmp_path / "s.md").write_text("---\ntitle: Hello\n---\n\nText.\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"),
                   ScriptedClient([{"0": "Bonjour\nfoo: bar", "1": "Texte."}]), "fr")

    assert target.read_text(encoding="utf-8").startswith('---\ntitle: "Bonjour\\nfoo: bar"\n---\n')


@pytest.mark.parametrize("text", [
    "a " + "`" * 20000,  # backtick runs nothing closes
    "](" * 20000,  # link openings with no end
    "\n" * 20000 + "a\n" * 20000,  # many lines after many blank lines
    ">\n" * 20000 + "> text\n" + ">\n" * 20000,  # a blockquote's blank lines
    "| " + "`a" * 50000 + " |\n|---|\n",  # a table row full of backticks
])
def test_untrusted_documents_take_linear_time(tmp_path, text):
    (tmp_path / "s.md").write_text(text, encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")

    started = time.perf_counter()
    for unit in markdown.untranslated_units():
        markdown.find_problem(unit.source, unit.source)
    assert time.perf_counter() - started < 2


def test_an_escaped_tag_cant_lose_its_backslash(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem(r"Write \<b> for bold", r"Écrivez \<b> pour le gras") is None
    assert markdown.find_problem(r"Write \<img src=x onerror=alert(1)>", "Écrivez <img src=x onerror=alert(1)>") \
        == "escapes"
    assert markdown.find_problem(r"Write \[click](javascript:alert(1))", "Écrivez [click](javascript:alert(1))") \
        == "escapes"
    # Moved elsewhere, the escape would still be there, but the link text wouldn't be text any more
    assert markdown.find_problem(r"\[click](//evil.example) [note]", r"[click](//evil.example) \[note]") == "links"
    # or the tag it escaped wouldn't be
    assert markdown.find_problem(r"Write \<img src=x onerror=alert(1)> and <b>bold</b>.",
                                 r"Écrivez <img src=x onerror=alert(1)> et \<b>gras</b>.") == "escapes"


def test_a_link_inside_another_keeps_the_outer_one_text(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    # A link's text can't hold a link, so the outer brackets are text and //evil.example isn't a link
    assert markdown.find_problem("[outer [inner](/safe)](//evil.example)",
                                 "[extérieur](//evil.example) [intérieur](/safe)") == "links"
    assert markdown.find_problem("![outer [inner](/safe)](cat.png)", "![extérieur [intérieur](/safe)](cat.png)") \
        is None


def test_a_link_ends_where_commonmark_ends_it(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    # \" doesn't end the title, which is never closed, so [b](//evil.example) is the link
    assert markdown.find_problem("See [a](/safe).", r'Voir [a](/safe "[b](//evil.example)\").') == "links"
    # A ) in a title isn't the link's, nor one in <...>, where parentheses needn't balance
    assert markdown.find_problem("[a [b](c)](/x)", '[a](/x "y)z") [b](c)') == "links"
    assert markdown.find_problem("See [a](/ok).", "Voir [a](/ok ([c](//evil.example))).") == "links"
    assert markdown.find_problem("[a [b](c)](<x(>)", "[a](<x(>) [b](c)") == "links"
    # A [ in a link's destination doesn't start link text
    assert markdown.find_problem("[a](b[) c](/x)", "[a](b[) [c](/x)") == "links"
    assert markdown.find_problem('See [a](/x "y)z").', 'Voir [a](/x "y)z").') is None


def test_link_candidates_sharing_spaces_take_linear_time(docs):
    text = "[a](" * 3000 + " " * 100_000 + "x" + ")" * 3000

    started = time.perf_counter()
    open_file(docs / "fr" / "guide.md").find_problem(text, text)
    assert time.perf_counter() - started < 1


def test_a_label_and_colon_before_text_is_a_paragraph(tmp_path):
    (tmp_path / "s.md").write_text("[Deprecated]: Use the new API.\n\n[docs]: /x\n  'Title'\n\nSee [docs].\n",
                                   encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")

    units = markdown.untranslated_units()

    assert [unit.source for unit in units] == ["[Deprecated]: Use the new API.", "See [docs]."]


def test_a_shortcut_reference_may_escape_a_bracket(tmp_path):
    (tmp_path / "s.md").write_text("[a\\]b]: /target\n\nSee [a\\]b].\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    assert markdown.find_problem("See [a\\]b].", "Voir [a\\]c].") == "links"
    # After an escaped backslash, the bracket is a link's
    assert markdown.find_problem("See it \\].", "Voir \\\\[a\\]b].") == "links"


def test_a_definition_in_a_quote_makes_its_label_a_link(tmp_path):
    (tmp_path / "s.md").write_text("> See [the FAQ].\n>\n> [the FAQ]: /faq\n\nAlso [the FAQ].\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    assert markdown.find_problem("Also [the FAQ].", "Aussi [la FAQ].") == "links"


def test_a_fence_on_a_list_markers_line_is_copied(tmp_path):
    (tmp_path / "s.md").write_text('- ```python\n  print("Hello")\n  ```\n- Item\n', encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Item"]
    # Left open, it ends with the item
    (tmp_path / "s.md").write_text("- ```\n  code\n- Item\n", encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Item"]


def test_a_fence_in_a_quote_in_a_quote_is_copied(tmp_path):
    (tmp_path / "s.md").write_text("> > ```\n> > code\n> > ```\n> Text\n", encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Text"]


def test_a_quoted_front_matter_value_over_two_lines_is_copied(tmp_path):
    (tmp_path / "s.md").write_text('---\ntitle: "A title\ncontinued"\n---\n\nText.\n', encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Text."]


def test_a_definitions_title_takes_the_lines_it_spans(tmp_path):
    (tmp_path / "s.md").write_text("[a]: /x 'Long\ntitle'\n\n[b]: /y \"Title\"\n\"Hello\"\n", encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ['"Hello"']


def test_lines_opening_brackets_take_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("[\n" * 200000, encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 2


def test_a_title_from_the_next_line_takes_the_lines_it_spans(tmp_path):
    (tmp_path / "s.md").write_text('[a]: /url\n"A long\ntitle"\n\nText [a].\n', encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Text [a]."]


def test_a_table_cell_starting_with_a_hash_may_be_translated(tmp_path):
    (tmp_path / "s.md").write_text("| Plan | # of users |\n| --- | --- |\n| Free | 5 |\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    assert markdown.find_problem("# of users", "Nombre d'utilisateurs") is None


def test_a_first_cell_without_a_pipe_before_it_cant_start_a_block(tmp_path):
    (tmp_path / "s.md").write_text("Place | Name\n--- | ---\n1st | Alice\n", encoding="utf-8")
    target = tmp_path / "de" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"),
                   ScriptedClient([{"0": "Platz", "1": "Name", "2": "1.", "3": "Alice"}]), "de")

    assert target.read_text(encoding="utf-8") == "Platz | Name\n--- | ---\n1\\. | Alice\n"


def test_inline_syntax_starting_a_first_cell_is_kept(tmp_path):
    source = ("Option | Meaning\n--- | ---\n`--force` | Overwrite\n**Bold** | Strong\n~~old~~ | Removed\n"
              "```` ```js ```` | Fence\n")
    (tmp_path / "s.md").write_text(source, encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_text(encoding="utf-8") == source


def test_a_rule_after_a_list_stays_a_rule(tmp_path):
    (tmp_path / "s.md").write_text("- one\n- two\n---\n\nNext\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(), "fr")

    assert target.read_text(encoding="utf-8") == "- T: one\n- T: two\n---\n\nT: Next\n"


def test_many_definitions_take_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("[a]: /x\n" * 200000, encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 2


def test_a_definitions_title_may_start_its_own_line(tmp_path):
    (tmp_path / "s.md").write_text('[docs]: /guide\n"The guide"\n\nText.\n', encoding="utf-8")
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["Text."]


def test_front_matter_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("---\ntitle: A" + " " * 200000 + "B\n---\n", encoding="utf-8")

    started = time.perf_counter()
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1
    assert units[0].source == "A" + " " * 200000 + "B"


def test_a_label_matches_its_definition_whatever_its_spacing(tmp_path):
    (tmp_path / "s.md").write_text("Hello\n\n[read the docs]: /evil\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    assert markdown.find_problem("Hello", "Bonjour [Read  the\tdocs]") == "links"


def test_a_code_span_may_end_with_a_backslash(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem("Open `C:\\`", "Ouvrez `C:\\`") is None
    assert markdown.find_problem("Open `C:\\`", "Ouvrez `D:\\`") == "inline code"


def test_a_translation_cant_open_a_code_block(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem("Hello", "Bonjour\n~~~") == "code blocks"
    assert markdown.find_problem("Hello", "Bonjour\n> ```") == "code blocks"


def test_a_translation_cant_add_a_heading(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem("Some text.", "Du texte.\n---") == "headings"
    assert markdown.find_problem("Item one", "Élément un\n# Titre") == "headings"


def test_a_heading_stays_on_one_line(tmp_path):
    (tmp_path / "s.md").write_text("# Install\n\nText.\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"),
                   ScriptedClient([{"0": "Installer\nAvant de commencer", "1": "Texte."}]), "fr")

    assert target.read_text(encoding="utf-8") == "# Installer Avant de commencer\n\nTexte.\n"


def test_a_carriage_return_in_a_translation_ends_a_line_as_a_newline_does(tmp_path):
    (tmp_path / "s.md").write_text("# Install\n\n> Note\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"),
                   ScriptedClient([{"0": "Installer\r# Titre", "1": "Remarque\rsuite"}]), "fr")

    # Renderers take a \r alone for a line break: the heading stays on its line, and the quote's lines in it
    assert target.read_text(encoding="utf-8") == "# Installer # Titre\n\n> Remarque\n> suite\n"


def test_a_label_and_colon_alone_is_text_unless_a_destination_follows(tmp_path):
    (tmp_path / "s.md").write_text("[foo]:\nSee the docs.\n", encoding="utf-8")

    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert [unit.source for unit in units] == ["[foo]:\nSee the docs."]


def test_a_definition_with_its_destination_on_the_next_line_is_kept(tmp_path):
    (tmp_path / "s.md").write_text("See [docs].\n\n[docs]:\n  /guide\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")

    assert [unit.source for unit in markdown.untranslated_units()] == ["See [docs]."]
    assert markdown.find_problem("See [docs].", "Voir [documentation].") == "links"


@pytest.mark.parametrize("value", ["Yes", "On", "2026", "null", "1.5", "2026-10-31"])
def test_front_matter_values_yaml_would_read_as_other_types_are_quoted(tmp_path, value):
    (tmp_path / "s.md").write_text("---\ntitle: Oui\n---\n\nText.\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"),
                   ScriptedClient([{"0": value, "1": "Texte."}]), "fr")

    assert target.read_text(encoding="utf-8").startswith(f'---\ntitle: "{value}"\n---\n')


def test_many_labels_are_checked_quickly(tmp_path):
    labels = 2000
    (tmp_path / "s.md").write_text("".join(f"See [l{i}].\n\n" for i in range(labels))
                                   + "".join(f"[l{i}]: /x{i}\n" for i in range(labels)), encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    started = time.perf_counter()
    problems = {markdown.find_problem(f"See [l{i}].", f"Voir [l{i}].") for i in range(labels)}
    assert problems == {None} and time.perf_counter() - started < 2
    assert markdown.find_problem("See [l1].", "Voir [l2].") == "links"


def test_an_escaped_backtick_cant_turn_code_into_html(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem("`<img src=x onerror=alert(1)>`", "\\`<img src=x onerror=alert(1)>`") is not None


def test_collapsed_references_keep_their_label(tmp_path):
    (tmp_path / "s.md").write_text("[Alpha][] and [Beta][]\n\n[Alpha]: /safe\n[Beta]: /evil\n", encoding="utf-8")
    markdown = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md")
    markdown.untranslated_units()

    assert markdown.find_problem("[Alpha][]", "[Beta][]") == "links"
    assert markdown.find_problem("[Alpha][] here", "[Alpha][] ici") is None


def test_unclosed_tags_take_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("<a " + "<" * 200000 + "\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1


def test_a_heading_with_a_long_run_of_spaces_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("# x" + " " * 200000 + "y\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1


@pytest.mark.parametrize("block", ["[" + "\\[" * 100000, "](" * 100000])
def test_checking_brackets_takes_linear_time(docs, block):
    markdown = open_file(docs / "fr" / "guide.md")

    started = time.perf_counter()
    markdown.find_problem(block, block)
    assert time.perf_counter() - started < 1


def test_a_long_line_of_spaces_after_a_table_candidate_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("| heading |\n" + " " * 200000 + "\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1


def test_front_matter_comments_stay_after_the_value(tmp_path):
    (tmp_path / "s.md").write_text('---\ntitle: "Hello" # shown in the nav\ndescription: Plain # a note\n---\n\n'
                                   "Text.\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"
    units = open_file(target, source_path=tmp_path / "s.md").untranslated_units()

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix="FR "), "fr")

    assert [unit.source for unit in units] == ["Hello", "Plain", "Text."]
    assert target.read_text(encoding="utf-8").startswith(
        '---\ntitle: "FR Hello" # shown in the nav\ndescription: FR Plain # a note\n---\n')


def test_an_escape_naming_no_character_is_left_as_written(tmp_path):
    (tmp_path / "s.md").write_text('---\ntitle: "Bad \\UFFFFFFFF"\n---\n\nText.\n', encoding="utf-8")

    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()

    assert units[0].source == "Bad \\UFFFFFFFF"


def test_a_link_cant_hide_behind_brackets_that_only_look_like_one(docs):
    markdown = open_file(docs / "fr" / "guide.md")

    assert markdown.find_problem("See [the guide](guide.md).",
                                 "Voir [le guide](guide.md [connexion](//evil.example) ici.") == "links"
