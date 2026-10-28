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
    code = lang_code.lower().replace("_", "-")
    return LANGUAGE_NAMES.get(code) or LANGUAGE_NAMES.get(code.split("-")[0]) or lang_code
