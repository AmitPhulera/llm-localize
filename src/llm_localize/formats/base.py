"""Base class for translatable file formats."""
import abc
import json
import os
import secrets
import shutil

from llm_localize.validation import find_problem


class TranslationFile(abc.ABC):
    """One translation file in some format, opened for a single target language.

    Subclasses read their file into ``TranslationUnit`` objects, write
    translations back and save. The engine handles batching, prompting,
    validation and concurrency, and calls ``apply`` and ``save`` from one
    thread at a time, so subclasses needn't be thread safe.

    :cvar name: the name the format is registered under, e.g. ``"po"``
    :cvar extensions: file extensions to detect the format by, e.g. ``(".po",)``
    :cvar instructions: format-specific guidance added to the prompt
    """

    name = None
    extensions = ()
    instructions = ""

    def __init__(self, path):
        self.path = str(path)

    @classmethod
    def open(cls, path, language=None, source_language=None, source_path=None):
        """Open ``path`` for translating to ``language``.

        Formats that keep the source text in the file, like PO, need only
        the path. Formats that keep each language in its own file use the
        rest to find the source file.
        """
        return cls(path)

    @property
    def language(self):
        """Return the file's target language if the file says, otherwise None."""
        return None

    @abc.abstractmethod
    def untranslated_units(self):
        """Return the ``TranslationUnit`` objects that need translating."""

    @abc.abstractmethod
    def apply(self, key, translation):
        """Write a translation into the file in memory.

        ``translation`` is a string, or for plural units, a dict mapping
        each ``PluralForm.index`` to its string.
        """

    @abc.abstractmethod
    def save(self):
        pass

    def find_problem(self, source, translation):
        """Return a short reason ``translation`` is unacceptable for ``source``, or None.

        Reasons are counted in the run's summary, so keep them to a few
        words, like ``"placeholders"``.
        """
        return find_problem(source, translation)

    def cleanup(self):
        """Clear saved translations that are broken in ways only the file format can detect.

        Runs after translating. Returns how many translations were cleared.
        """
        return 0


def write_file(path, data):
    """Write ``data`` (bytes) to ``path`` only once it is all written, so a failure leaves the file as it was.

    The data goes to a temporary file beside it, which then replaces it,
    keeping its permissions; a symlink stays a link to the updated file.
    Missing directories are created.
    """
    path = os.path.realpath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Part of the name only, so a long but valid one doesn't make the temporary name too long
    temporary = os.path.join(os.path.dirname(path), f".{os.path.basename(path)[:50]}.{secrets.token_hex(8)}.tmp")
    # Mode 0o666 less the umask, as open() gives a new file; mkstemp's would be 0o600
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if os.path.exists(path):
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


# Deeper than any translation file nests, and shallow enough for the code that walks a document
MAX_JSON_DEPTH = 100


def load_json(text, path):
    """Return a JSON document, raising ValueError, naming ``path``, if it's invalid or nests too deeply.

    >>> load_json('{"a": [1, {"b": 2}]}', "x.json")
    {'a': [1, {'b': 2}]}
    >>> load_json("[" * 101 + "]" * 101, "x.json")
    Traceback (most recent call last):
    ValueError: x.json nests objects or arrays more than 100 deep
    """
    too_deep = ValueError(f"{path} nests objects or arrays more than {MAX_JSON_DEPTH} deep")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    except RecursionError:
        raise too_deep from None
    # Only objects and arrays are walked, so a big file's strings and numbers aren't each visited
    stack = [(document, 1)] if isinstance(document, (dict, list)) else []
    while stack:
        value, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise too_deep
        stack.extend((item, depth + 1) for item in (value.values() if isinstance(value, dict) else value)
                     if isinstance(item, (dict, list)))
    return document


def splice(data, replacements):
    """Return ``data`` (bytes or text) with each ``(start, end, new)`` replacement made, in one pass.

    Making them one at a time would copy the rest of the file for each. An
    insertion, where start is end, goes before a replacement at the same place.

    >>> splice(b"Hello world", [(6, 11, b"there"), (0, 0, b"> "), (5, 5, b",")])
    b'> Hello, there'
    """
    pieces, previous = [], 0
    for start, end, new in sorted(replacements, key=lambda replacement: replacement[:2]):
        pieces += [data[previous:start], new]
        previous = end
    return data[:0].join(pieces) + data[previous:]
