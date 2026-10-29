"""CLDR plural categories, for formats that name plural forms ``one``, ``few``, ``many``, ``other``.

The table in ``data/plurals.json`` lists, for each language, the
categories it uses for whole numbers and sample numbers for each, from
the Unicode CLDR (cldr-json 48.2.0, supplemental/plurals.json), under
the Unicode license in licenses/Unicode-LICENSE.txt. Samples written in
compact notation (1c6) are left out, and "…" ends a list that goes on.
"""
import functools
import json
from importlib import resources

# For languages CLDR doesn't know: English-style singular and plural
DEFAULT_CATEGORIES = {"one": "1", "other": "0, 2~16, 100, 1000, …"}


@functools.cache
def _table(name="plurals"):
    return json.loads(resources.files("llm_localize").joinpath(f"data/{name}.json").read_text("utf-8"))


def _lookup(table, language):
    """Return ``table``'s entry for ``language``, falling back from a regional variant to its language."""
    code = language.lower().replace("_", "-")
    while code:
        if code in table:
            return table[code]
        code = code.rpartition("-")[0]
    return None


def plural_categories(language):
    """Return ``{category: sample whole numbers}`` for a language, in CLDR order.

    Regional variants fall back to their language, and unknown languages
    to English-style ``one`` and ``other``.

    >>> list(plural_categories("ru"))
    ['one', 'few', 'many', 'other']
    >>> list(plural_categories("pt_PT")), list(plural_categories("ja"))
    (['one', 'many', 'other'], ['other'])
    >>> plural_categories("xx") == DEFAULT_CATEGORIES
    True
    """
    return _lookup(_table(), language) or DEFAULT_CATEGORIES
