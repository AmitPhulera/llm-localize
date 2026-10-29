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

from llm_localize.languages import normalize
from llm_localize.units import PluralForm

CATEGORIES = ("zero", "one", "two", "few", "many", "other")

# For languages CLDR doesn't know: English-style singular and plural
DEFAULT_CATEGORIES = {"one": "1", "other": "0, 2~16, 100, 1000, …"}


@functools.cache
def _table(name="plurals"):
    return json.loads(resources.files("llm_localize").joinpath(f"data/{name}.json").read_text("utf-8"))


def _lookup(table, language):
    """Return ``table``'s entry for ``language``, falling back from a regional variant to its language."""
    code = normalize(language)
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


def has_rules(language):
    """Return True if CLDR has plural rules for the language ``language`` (a bare code like ``"fr"``)."""
    return language.lower() in _table()


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


# The script a language is written in when its code doesn't name one, where it has more than one:
# by its region, then for the language
IMPLIED_SCRIPTS = {"zh-tw": "hant", "zh-hk": "hant", "zh-mo": "hant", "zh": "hans", "sr-me": "latn", "sr": "cyrl"}


def _script(code):
    """Return the script a normalized code names or implies, or "" if it may be any.

    >>> _script("zh-hant"), _script("zh-hk"), _script("zh-cn"), _script("sr-latn"), _script("pt-br")
    ('hant', 'hant', 'hans', 'latn', '')
    """
    tags = code.split("-")
    scripts = [tag for tag in tags[1:] if len(tag) == 4 and tag.isalpha()]
    if scripts:
        return scripts[0]
    regions = [tag for tag in tags[1:] if len(tag) == 2]
    return IMPLIED_SCRIPTS.get(f"{tags[0]}-{regions[0]}" if regions else "", IMPLIED_SCRIPTS.get(tags[0], ""))


def compatible_languages(declared, given):
    """True if a file declared as one language can be translated to another.

    They must be the same language with the same plural rules, as the
    file's plural forms are the declared one's, and not name different
    scripts. A region or variant may differ.

    >>> [compatible_languages(a, b) for a, b in [("zh_CN", "zh-Hans"), ("es_ES", "es-419"), ("pt", "pt-BR")]]
    [True, True, True]
    >>> pairs = [("pt_BR", "pt-PT"), ("zh_Hans", "zh-Hant"), ("sr@latin", "sr-Cyrl"), ("zh_TW", "zh-Hans"),
    ...          ("sr", "sr-Latn")]
    >>> [compatible_languages(declared, given) for declared, given in pairs]
    [False, False, False, False, False]
    >>> compatible_languages("uz", "uz-Latn")
    True
    """
    declared, given = normalize(declared), normalize(given)
    if declared.split("-")[0] != given.split("-")[0]:
        return False
    scripts = _script(declared), _script(given)
    if all(scripts) and scripts[0] != scripts[1]:
        return False
    return gettext_plural_forms(declared) == gettext_plural_forms(given)
