"""CLDR plural categories, for formats that name plural forms ``one``, ``few``, ``many``, ``other``.

The table in ``data/plurals.json`` lists, for each language, the
categories it uses for whole numbers and sample numbers for each, from
the Unicode CLDR (cldr-json 48.2.0, supplemental/plurals.json), under
the Unicode license in licenses/Unicode-LICENSE.txt. Samples written in
compact notation (1c6) are left out, and "…" ends a list that goes on.
``data/ordinals.json`` lists ordinal categories (1st, 2nd) the same way,
from supplemental/ordinals.json. ``data/gettext_plurals.json`` holds a
gettext ``Plural-Forms`` header per language, made from the same CLDR
rules for whole numbers (gettext's ``n`` is one): the fraction and
exponent operands are 0, categories only fractions use are left out, and
the rest keep CLDR's order as their index.
"""
import functools
import json
from importlib import resources

from llm_localize.units import PluralForm

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


def ordinal_categories(language):
    """Return ``{category: sample whole numbers}`` for a language's ordinals, or None if CLDR doesn't know it.

    >>> list(ordinal_categories("en")), list(ordinal_categories("ru"))
    (['one', 'two', 'few', 'other'], ['other'])
    >>> ordinal_categories("xx") is None
    True
    """
    return _lookup(_table("ordinals"), language)


def plural_forms(language):
    """Return a ``PluralForm`` per CLDR category of ``language``, indexed by category name.

    >>> few = plural_forms("ru")[1]
    >>> few.index, few.description
    ('few', 'used when n is 2-4, 22-24, 32-34, 42-44, 52-54, 62, 102, 1002, ...')
    >>> plural_forms("ru")[3].description
    'used only for fractions, like 1.5'
    >>> plural_forms("en")[0].singular, plural_forms("fr")[0].singular
    (True, False)
    """
    return tuple(
        PluralForm(index=category, description=_describe(samples), singular=samples == "1")
        for category, samples in plural_categories(language).items()
    )


def _describe(samples):
    if not samples:
        return "used only for fractions, like 1.5"
    return f"used when n is {samples.replace('~', '-').replace('…', '...')}"


def gettext_plural_forms(language):
    """Return a gettext ``Plural-Forms`` header for a language, from CLDR, or None if CLDR doesn't know it.

    >>> gettext_plural_forms("pt_BR")
    'nplurals=3; plural=(n>=0 && n<=1) ? 0 : (n!=0 && n%1000000==0) ? 1 : 2;'
    >>> gettext_plural_forms("ja"), gettext_plural_forms("xx")
    ('nplurals=1; plural=0;', None)
    """
    return _lookup(_table("gettext_plurals"), language)
