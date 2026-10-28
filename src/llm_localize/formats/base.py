"""Base class for translatable file formats."""
import abc

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
