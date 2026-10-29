"""Android string resources: ``res/values/strings.xml`` and its translations, like ``res/values-fr/strings.xml``.
"""
import re
from pathlib import Path

from llm_localize.formats.monolingual import _is_language_code


def _values_dir(path):
    """Return ``(part index, language, other qualifiers)`` for the ``values-`` directory naming a language.

    >>> _values_dir("res/values-pt-rBR/strings.xml"), _values_dir("res/values-b+sr+Latn-land/strings.xml")
    ((1, 'pt-BR', []), (1, 'sr-Latn', ['land']))
    >>> _values_dir("res/values-night/strings.xml") is None
    True
    """
    parts = Path(path).parts
    for part_index in reversed(range(len(parts))):
        qualifiers = parts[part_index].split("-")
        if qualifiers[0] != "values":
            continue
        for index, qualifier in enumerate(qualifiers[1:], start=1):
            if qualifier.startswith("b+"):
                return part_index, "-".join(qualifier[2:].split("+")), qualifiers[1:index] + qualifiers[index + 1:]
            if qualifier.islower() and _is_language_code(qualifier):
                language, end = qualifier, index + 1
                if end < len(qualifiers) and re.fullmatch(r"r[A-Z]{2}", qualifiers[end]):
                    language, end = f"{qualifier}-{qualifiers[end][1:]}", end + 1
                return part_index, language, qualifiers[1:index] + qualifiers[end:]
    return None
