import time

import pytest

from llm_localize.cli import main
from llm_localize.engine import translate_file
from llm_localize.formats import open_file
from llm_localize.formats.markdown import MarkdownFile

from .fakes import FakeClient

GUIDE = '''# Getting started

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

```bash
acme --help
```

    indented code

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
        ("Getting started", ""),
        ('Welcome to **Acme**. Read the [guide](https://example.com/guide "Guide") or the [FAQ][faq].\n'
         "This line wraps.", "Section: Getting started"),
        ("Install", "Section: Getting started"),
        ("Run `pip install acme`.", "Section: Getting started > Install"),
        ("Open the app\nand sign in.", "Section: Getting started > Install"),
        ("Nested item with [the docs].", "Section: Getting started > Install"),
        ("**Note:** keep your key secret.\n\nIt's in `~/.acme`.", "Section: Getting started > Install"),
        ("Setext heading", "Section: Getting started"),
        ("Todo item", "Section: Getting started > Setext heading"),
    ]


def test_translations_keep_the_structure(docs):
    path = docs / "fr" / "guide.md"

    result = translate_file(open_file(path), FakeClient(), "fr")

    assert result.translated == 9
    text = path.read_text(encoding="utf-8")
    assert "2. T: Open the app\n   and sign in.\n   - T: Nested item with [the docs].\n" in text
    assert "> T: **Note:** keep your key secret.\n>\n> It's in `~/.acme`.\n" in text
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

    assert capsys.readouterr().out == f"{path} (de): translated 9 of 9\n"


def test_the_source_itself_is_left_alone(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    path = tmp_path / "docs" / "en" / "guide.md"
    path.write_text("# Hello\n")

    result = translate_file(open_file(path, source_language="en"), FakeClient(), "en")

    assert (result.untranslated, path.read_text()) == (0, "# Hello\n")


def test_code_inside_a_list_item_is_not_translated(tmp_path):
    (tmp_path / "guide.md").write_text('- Example\n\n      print("Hello")\n\n  More about it.\n')

    units = open_file(tmp_path / "fr" / "guide.md").untranslated_units()

    assert [unit.source for unit in units] == ["Example", "More about it."]


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
"""


def test_code_in_list_items_is_not_translated(tmp_path):
    (tmp_path / "code.md").write_text(CODE_IN_CONTAINERS, encoding="utf-8")
    target = tmp_path / "fr" / "code.md"

    units = open_file(target, source_path=tmp_path / "code.md").untranslated_units()
    translate_file(open_file(target, source_path=tmp_path / "code.md"), FakeClient(), "fr")

    assert [unit.source for unit in units] == [
        "Install:", "Run it", "Item"]
    assert target.read_text(encoding="utf-8") == (
        CODE_IN_CONTAINERS.replace("Install:", "T: Install:").replace("Run it", "T: Run it")
        .replace("- Item", "- T: Item"))


def test_code_in_containers_round_trips(tmp_path):
    (tmp_path / "code.md").write_text(CODE_IN_CONTAINERS, encoding="utf-8")
    target = tmp_path / "fr" / "code.md"

    translate_file(open_file(target, source_path=tmp_path / "code.md"), FakeClient(prefix=""), "fr")

    assert target.read_text(encoding="utf-8") == CODE_IN_CONTAINERS


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_only_line_endings_end_lines(tmp_path, newline):
    source = newline.join(["# Title", "", "First line second line,", "next\x0cpage", "- item one",
                           "  goes on", "", "> quoted", "> lines", "", "```", "code\x85here", "```", ""])
    (tmp_path / "s.md").write_text(source, encoding="utf-8", newline="")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_bytes().decode() == source


@pytest.mark.parametrize("text", [
    "\n" * 20000 + "a\n" * 20000,  # many lines after many blank lines
    ">\n" * 20000 + "> text\n" + ">\n" * 20000,  # a blockquote's blank lines
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


def test_a_rule_after_a_list_stays_a_rule(tmp_path):
    (tmp_path / "s.md").write_text("- one\n- two\n---\n\nNext\n", encoding="utf-8")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(), "fr")

    assert target.read_text(encoding="utf-8") == "- T: one\n- T: two\n---\n\nT: Next\n"


def test_a_heading_with_a_long_run_of_spaces_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("# x" + " " * 200000 + "y\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1
