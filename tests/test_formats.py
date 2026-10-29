import os

import pytest

from llm_localize.formats import format_class_for_path, get_format_class, open_file
from llm_localize.formats.base import write_file
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


class TestWriteFile:

    def test_a_failed_write_leaves_the_file_as_it_was(self, tmp_path, monkeypatch):
        path = tmp_path / "fr.json"
        path.write_text('{"a": "Bonjour"}')

        def fail(*args):
            raise OSError("disk full")
        monkeypatch.setattr(os, "replace", fail)
        with pytest.raises(OSError, match="disk full"):
            write_file(path, b"{}")

        assert path.read_text() == '{"a": "Bonjour"}'
        assert [p.name for p in tmp_path.iterdir()] == ["fr.json"]

    def test_keeps_the_mode_and_symlinks(self, tmp_path):
        real = tmp_path / "real.json"
        real.write_text("{}")
        real.chmod(0o640)
        link = tmp_path / "fr.json"
        link.symlink_to(real)

        write_file(link, b'{"a": 1}')

        assert link.is_symlink() and real.read_text() == '{"a": 1}'
        assert real.stat().st_mode & 0o777 == 0o640

    def test_creates_directories_and_gives_new_files_the_usual_mode(self, tmp_path):
        path = tmp_path / "res" / "values-fr" / "strings.xml"
        umask = os.umask(0)
        os.umask(umask)

        write_file(path, b"<resources/>")

        assert path.read_bytes() == b"<resources/>"
        assert path.stat().st_mode & 0o777 == 0o666 & ~umask

    def test_new_files_follow_the_umask_set_after_import(self, tmp_path):
        umask = os.umask(0o077)
        try:
            write_file(tmp_path / "fr.json", b"{}")
        finally:
            os.umask(umask)

        assert (tmp_path / "fr.json").stat().st_mode & 0o777 == 0o600

    def test_a_long_name_is_written(self, tmp_path):
        path = tmp_path / ("a" * 240 + ".json")

        write_file(path, b"{}")

        assert path.read_bytes() == b"{}"
