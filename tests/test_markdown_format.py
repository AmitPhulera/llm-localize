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

```bash
acme --help
```

Setext heading
--------------

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
        ("Setext heading", "Section: Getting started"),
    ]


def test_translations_keep_the_structure(docs):
    path = docs / "fr" / "guide.md"

    result = translate_file(open_file(path), FakeClient(), "fr")

    assert result.translated == 4
    text = path.read_text(encoding="utf-8")
    assert "```bash\nacme --help\n```\n" in text
    assert "T: Setext heading\n--------------\n" in text


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

    assert capsys.readouterr().out == f"{path} (de): translated 4 of 4\n"


def test_the_source_itself_is_left_alone(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    path = tmp_path / "docs" / "en" / "guide.md"
    path.write_text("# Hello\n")

    result = translate_file(open_file(path, source_language="en"), FakeClient(), "en")

    assert (result.untranslated, path.read_text()) == (0, "# Hello\n")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_only_line_endings_end_lines(tmp_path, newline):
    source = newline.join(["# Title", "", "First line second line,", "next\x0cpage", "",
                           "```", "code\x85here", "```", ""])
    (tmp_path / "s.md").write_text(source, encoding="utf-8", newline="")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_bytes().decode() == source


def test_a_heading_with_a_long_run_of_spaces_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("# x" + " " * 200000 + "y\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1
