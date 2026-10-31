"""Translate i18n files and strings with LLMs."""
# Before the imports, since cli imports it while this package is still loading
__version__ = "0.1.1"

from llm_localize.files import FileTranslator
from llm_localize.strings import StringTranslator

__all__ = ["FileTranslator", "StringTranslator"]
