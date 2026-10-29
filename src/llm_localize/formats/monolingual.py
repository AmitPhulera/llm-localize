"""Helpers for formats that keep each language's messages in a file of its own."""
from llm_localize.languages import LANGUAGE_NAMES
from llm_localize.plurals import has_rules


def _is_language_code(token, known=True):
    """Return True if ``token`` looks like a language code or locale name we know, like fr, pt_BR or zh-Hans.

    After the language, only a script and a region may follow, so a
    file named ``to_trans`` isn't taken for Tongan. With ``known`` False,
    any two- or three-letter language counts, like rw for Kinyarwanda,
    which neither Django nor CLDR's plural rules list.

    >>> [_is_language_code(t) for t in ["fr", "pt_BR", "zh-Hans", "en-US", "es-419", "sr-Latn-RS"]]
    [True, True, True, True, True, True]
    >>> [_is_language_code(t) for t in ["json", "messages", "app", "to_trans", "my_notes", "en-US-x"]]
    [False, False, False, False, False, False]
    >>> _is_language_code("rw"), _is_language_code("rw", known=False), _is_language_code("en-guide", known=False)
    (False, True, False)
    """
    base, *subtags = token.lower().replace("_", "-").split("-")
    if not 2 <= len(base) <= 3 or not base.isalpha():
        return False
    if known and base not in LANGUAGE_NAMES and not has_rules(base):
        return False
    if subtags and len(subtags[0]) == 4 and subtags[0].isalpha():
        subtags = subtags[1:]  # the script, like Hans
    return not subtags or (len(subtags) == 1 and (
        (len(subtags[0]) == 2 and subtags[0].isalpha()) or (len(subtags[0]) == 3 and subtags[0].isdigit())))
