import time

import pytest

from llm_localize.engine import translate_file
from llm_localize.formats import open_file

from .fakes import FakeClient

GUIDE = '''# Getting started

Welcome to **Acme**. Read the [guide](https://example.com/guide "Guide") or the [FAQ][faq].
This line wraps.

## Install
'''


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    (tmp_path / "docs" / "en" / "guide.md").write_text(GUIDE, encoding="utf-8")
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
    ]


def test_translations_keep_the_structure(docs):
    path = docs / "fr" / "guide.md"

    result = translate_file(open_file(path), FakeClient(), "fr")

    assert result.translated == 3
    text = path.read_text(encoding="utf-8")
    assert "# T: Getting started\n\nT: Welcome to **Acme**." in text


def test_the_source_itself_is_left_alone(tmp_path):
    (tmp_path / "docs" / "en").mkdir(parents=True)
    path = tmp_path / "docs" / "en" / "guide.md"
    path.write_text("# Hello\n")

    result = translate_file(open_file(path, source_language="en"), FakeClient(), "en")

    assert (result.untranslated, path.read_text()) == (0, "# Hello\n")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_only_line_endings_end_lines(tmp_path, newline):
    source = newline.join(["# Title", "", "First line second line,", "next\x0cpage", ""])
    (tmp_path / "s.md").write_text(source, encoding="utf-8", newline="")
    target = tmp_path / "fr" / "s.md"

    translate_file(open_file(target, source_path=tmp_path / "s.md"), FakeClient(prefix=""), "fr")

    assert target.read_bytes().decode() == source


def test_a_heading_with_a_long_run_of_spaces_takes_linear_time(tmp_path):
    (tmp_path / "s.md").write_text("# x" + " " * 200000 + "y\n", encoding="utf-8")

    started = time.perf_counter()
    open_file(tmp_path / "fr" / "s.md", source_path=tmp_path / "s.md").untranslated_units()
    assert time.perf_counter() - started < 1
