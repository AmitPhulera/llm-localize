"""Registry of translatable file formats.

A format is named either by a key in ``FORMATS`` or by the dotted path
to a ``TranslationFile`` subclass, e.g. ``"myproject.formats.YamlFile"``.
"""
from pathlib import Path

from llm_localize.formats.base import TranslationFile
from llm_localize.utils import import_class

FORMATS = {
    'po': 'llm_localize.formats.po.PoFile',
    'json': 'llm_localize.formats.json_format.JsonFile',
    'android': 'llm_localize.formats.android.AndroidFile',
    'strings': 'llm_localize.formats.ios.StringsFile',
    'xcstrings': 'llm_localize.formats.ios.XcstringsFile',
    'xliff': 'llm_localize.formats.xliff.XliffFile',
}


def get_format_class(name):
    try:
        return import_class(FORMATS.get(name, name), TranslationFile)
    except ImportError as e:
        raise ValueError(f"Unknown translation format {name!r}: {e}") from e


def format_class_for_path(path, formats=None):
    """Return the format class whose extensions match ``path``.

    :param formats: format names or dotted paths to consider; defaults to
        every format in ``FORMATS``
    """
    suffix = Path(path).suffix.lower()
    for name in formats or FORMATS:
        format_class = get_format_class(name)
        if suffix in format_class.extensions:
            return format_class
    raise ValueError(f"No translation format registered for {path} (extension {suffix!r})")


def open_file(path, format=None, formats=None, language=None, source_language=None, source_path=None):
    """Open a translation file, detecting its format from its extension unless ``format`` is given.

    ``language``, ``source_language`` and ``source_path`` are passed to
    ``TranslationFile.open``, for formats that keep each language in its own file.
    """
    format_class = get_format_class(format) if format else format_class_for_path(path, formats)
    return format_class.open(path, language=language, source_language=source_language, source_path=source_path)
