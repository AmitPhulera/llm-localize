import pytest

from llm_localize.formats import format_class_for_path, get_format_class, open_file
from llm_localize.formats.po import PoFile

from .fakes import DictFile


def test_detect_by_extension(tmp_path):
    path = tmp_path / "django.po"
    path.write_text("")

    assert isinstance(open_file(path), PoFile)


def test_explicit_format():
    assert isinstance(open_file("x.txt", format="tests.fakes.DictFile"), DictFile)


def test_custom_formats_are_detected_when_listed():
    assert format_class_for_path("x.dict", formats=["po", "tests.fakes.DictFile"]) is DictFile


@pytest.mark.parametrize("name", ["nope", "tests.fakes.FakeClient"])
def test_unknown_format(name):
    with pytest.raises(ValueError):
        get_format_class(name)


def test_pot_templates_are_not_translatable():
    with pytest.raises(ValueError, match="No translation format"):
        open_file("messages.pot")


def test_unknown_extension():
    with pytest.raises(ValueError, match="No translation format"):
        open_file("strings.yaml")
