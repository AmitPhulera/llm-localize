"""Language code helpers."""

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
    >>> language_name("en-us")
    'English'
    >>> language_name("am")
    'am'
    """
    code = normalize(lang_code)
    return LANGUAGE_NAMES.get(code) or LANGUAGE_NAMES.get(code.split("-")[0]) or lang_code


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
