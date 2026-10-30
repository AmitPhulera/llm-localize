"""Language code helpers.

Languages are named from Django's table below and, for the many it
doesn't list, from ``data/language_names.json``: the English names the
Unicode CLDR gives each language and variant (cldr-json 48.2.0,
cldr-localenames-full/main/en/languages.json), keyed by lowercase code,
under the Unicode license in licenses/Unicode-LICENSE.txt.
"""
import argparse
import functools
import json
import re
from importlib import resources

# A language code or locale name: a 2-3 letter language, then subtags like zh-Hans, pt_BR or nl_NL-x-informal
LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8})*")

# English names of the languages Django supports, by language code, from
# Django's LANG_INFO (django/conf/locale/__init__.py), with fallbacks like
# zh-cn -> zh-hans resolved. Django is BSD-licensed; see
# licenses/Django-LICENSE.txt.
LANGUAGE_NAMES = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "ar-dz": "Algerian Arabic",
    "ast": "Asturian",
    "az": "Azerbaijani",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "br": "Breton",
    "bs": "Bosnian",
    "ca": "Catalan",
    "ckb": "Central Kurdish (Sorani)",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "dsb": "Lower Sorbian",
    "el": "Greek",
    "en": "English",
    "en-au": "Australian English",
    "en-gb": "British English",
    "eo": "Esperanto",
    "es": "Spanish",
    "es-ar": "Argentinian Spanish",
    "es-co": "Colombian Spanish",
    "es-mx": "Mexican Spanish",
    "es-ni": "Nicaraguan Spanish",
    "es-ve": "Venezuelan Spanish",
    "et": "Estonian",
    "eu": "Basque",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Frisian",
    "ga": "Irish",
    "gd": "Scottish Gaelic",
    "gl": "Galician",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hsb": "Upper Sorbian",
    "ht": "Haitian Creole",
    "hu": "Hungarian",
    "hy": "Armenian",
    "ia": "Interlingua",
    "id": "Indonesian",
    "ig": "Igbo",
    "io": "Ido",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kab": "Kabyle",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "ky": "Kyrgyz",
    "lb": "Luxembourgish",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "my": "Burmese",
    "nb": "Norwegian Bokmal",
    "ne": "Nepali",
    "nl": "Dutch",
    "nn": "Norwegian Nynorsk",
    "no": "Norwegian",
    "os": "Ossetic",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sr": "Serbian",
    "sr-latn": "Serbian Latin",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tajik",
    "th": "Thai",
    "tk": "Turkmen",
    "tr": "Turkish",
    "tt": "Tatar",
    "udm": "Udmurt",
    "ug": "Uyghur",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "zh-cn": "Simplified Chinese",
    "zh-hans": "Simplified Chinese",
    "zh-hant": "Traditional Chinese",
    "zh-hk": "Traditional Chinese",
    "zh-mo": "Traditional Chinese",
    "zh-my": "Simplified Chinese",
    "zh-sg": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
}


def normalize(code):
    """Return a language code or locale name lower-cased and hyphenated, as the tables key them.

    gettext's ``@latin`` and ``@cyrillic`` become scripts, other modifiers
    and a charset are dropped.

    >>> normalize("pt_BR"), normalize("sr@latin"), normalize("ca_ES.UTF-8@valencia"), normalize("zh-Hans")
    ('pt-br', 'sr-latn', 'ca-es', 'zh-hans')
    """
    code, _, modifier = code.partition("@")
    code = code.split(".")[0].lower().replace("_", "-")
    script = {"latin": "latn", "cyrillic": "cyrl"}.get(modifier.lower())
    return f"{code}-{script}" if script else code


def language_name(lang_code):
    """Return the English name for a language code, or the code itself if it isn't known.

    Accepts locale names (``pt_BR``) and regional variants of known
    languages (``en-us``). Models understand bare codes well, so an
    unknown code is good enough for the prompt.

    >>> language_name("fr")
    'French'
    >>> language_name("pt_BR")
    'Brazilian Portuguese'
    >>> language_name("en-us"), language_name("en-nz")
    ('American English', 'English')
    >>> language_name("am"), language_name("xx")
    ('Amharic', 'xx')
    """
    code = normalize(lang_code)
    base = code.split("-")[0]
    return (LANGUAGE_NAMES.get(code) or _cldr_names().get(code) or LANGUAGE_NAMES.get(base)
            or _cldr_names().get(base) or lang_code)


def language_code(language):
    """Return the code for a language given by its English name, or ``language`` itself if it's a code.

    It's the type of the command line's language options, so anything
    else, like a name neither table lists, is refused with
    ``argparse.ArgumentTypeError`` rather than taken for a code.

    >>> language_code("hindi"), language_code("Brazilian Portuguese"), language_code("fr"), language_code("rw")
    ('hi', 'pt-br', 'fr', 'rw')
    >>> language_code("Simplified Chinese"), language_code("Traditional Chinese"), language_code("sr_Latn")
    ('zh-hans', 'zh-hant', 'sr_Latn')
    >>> language_code("Amharic"), language_code("kinyarwanda"), language_code("Swiss High German")
    ('am', 'rw', 'de-ch')
    >>> language_code("ga"), language_code("Ga"), language_code("Irish"), language_code(" fr ")
    ('ga', 'Ga', 'ga', 'fr')
    >>> language_code("Klingonese")
    Traceback (most recent call last):
    argparse.ArgumentTypeError: unknown language 'Klingonese': give its code, like fr or pt-BR
    """
    language = language.strip()
    wanted = language.lower()
    # A code is taken as one, even where it's also a name, like ga (Irish), which CLDR calls Ga's gaa
    if wanted.replace("_", "-") in LANGUAGE_NAMES or wanted.replace("_", "-") in _cldr_names():
        return language
    # Django's names first, so its codes stay the ones given for the languages it lists
    codes = ([code for code, name in LANGUAGE_NAMES.items() if name.lower() == wanted]
             or [code for code, name in _cldr_names().items() if name.lower() == wanted])
    if codes:
        # Of codes sharing a name, one without a region: zh-hant rather than zh-hk or zh-tw
        return min(codes, key=lambda code: len(code.split("-")[-1]) == 2 and "-" in code)
    if not LANGUAGE_CODE_RE.fullmatch(language):
        raise argparse.ArgumentTypeError(f"unknown language {language!r}: give its code, like fr or pt-BR")
    return language


def same_language(code, other):
    """Return True if ``code`` names the same language as ``other``, or a variant of it.

    Accepts locale names (``pt_BR``) as well as language codes.

    >>> same_language("en", "en-us"), same_language("pt-br", "pt"), same_language("fr", "en")
    (True, False, False)
    """
    code, other = normalize(code), normalize(other)
    return code == other or other.startswith(f"{code}-")


def to_locale(language):
    """Turn a language code into a locale directory name, like Django's ``to_locale``.

    Locale names pass through unchanged.

    >>> to_locale("pt-br"), to_locale("zh-hans"), to_locale("fra"), to_locale("pt_BR")
    ('pt_BR', 'zh_Hans', 'fra', 'pt_BR')
    >>> to_locale("nl_NL-x-informal")
    'nl_NL-x-informal'
    """
    if "_" in language:
        return language
    code = language
    language, _, country = language.lower().partition("-")
    if not country:
        return code[:3].lower() + code[3:]
    country, _, rest = country.partition("-")
    country = country.title() if len(country) > 2 else country.upper()
    return f"{language}_{country}" + (f"-{rest}" if rest else "")


@functools.cache
def _cldr_names():
    return json.loads(resources.files("llm_localize").joinpath("data/language_names.json").read_text("utf-8"))
