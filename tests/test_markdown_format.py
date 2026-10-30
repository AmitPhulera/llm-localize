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


@pytest.mark.parametrize("text", [
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


def test_front_matter_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("---\ntitle: A" + " " * 200000 + "B\n---\n", encoding="utf-8")

    started = time.perf_counter()
    units = open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1
    assert units[0].source == "A" + " " * 200000 + "B"


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
