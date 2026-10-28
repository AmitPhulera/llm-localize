import pytest

from llm_localize.formats.po.plurals import counts_by_plural_index_from_header, nplurals_from_header

# Plural-Forms headers from real Django locale files
ENGLISH_PLURAL_FORMS = "nplurals=2; plural=(n != 1);"
FRENCH_PLURAL_FORMS = "nplurals=2; plural=(n > 1);"
SPANISH_PLURAL_FORMS = "nplurals=3; plural=n == 1 ? 0 : n != 0 && n % 1000000 == 0 ? 1 : 2;"
UKRAINIAN_PLURAL_FORMS = (
    "nplurals=4; plural=(n % 1 == 0 && n % 10 == 1 && n % 100 != 11 ? 0 : n % 1 == 0 && "
    "n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 1 : n % 1 == 0 && "
    "(n % 10 ==0 || (n % 10 >=5 && n % 10 <=9) || (n % 100 >=11 && n % 100 <=14 )) ? 2: 3);"
)
ARABIC_PLURAL_FORMS = (
    "nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : "
    "n%100>=11 && n%100<=99 ? 4 : 5;"
)


@pytest.mark.parametrize("header, expected", [
    pytest.param(ENGLISH_PLURAL_FORMS, {0: [1], 1: [0, 2, 3]}, id="english"),
    pytest.param(FRENCH_PLURAL_FORMS, {0: [0, 1], 1: [2, 3, 4]}, id="french"),
    pytest.param(SPANISH_PLURAL_FORMS, {0: [1], 1: [1000000, 2000000], 2: [0, 2, 3]}, id="spanish"),
    pytest.param(UKRAINIAN_PLURAL_FORMS, {0: [1, 21, 31], 1: [2, 3, 4], 2: [0, 5, 6], 3: []}, id="ukrainian"),
    pytest.param(ARABIC_PLURAL_FORMS, {0: [0], 1: [1], 2: [2], 3: [3, 4, 5], 4: [11, 12, 13], 5: [100, 101, 102]},
                 id="arabic"),
    pytest.param("", {0: [1], 1: [0, 2, 3]}, id="missing-header"),
])
def test_counts_by_plural_index_from_header(header, expected):
    counts = counts_by_plural_index_from_header(header)

    assert {plural_index: n[:3] for plural_index, n in counts.items()} == expected


@pytest.mark.parametrize("header, message", [
    ("nplurals=1; plural=(n != 1);", "gives index 1 for n=0"),
    ("nplurals=0; plural=0;", "nplurals must be at least 1"),
    ("nplurals=2; plural=(n%0==1);", "divides by zero"),
])
def test_inconsistent_header(header, message):
    with pytest.raises(ValueError, match=message):
        counts_by_plural_index_from_header(header)


def test_no_more_plural_forms_than_a_language_could_have():
    assert nplurals_from_header("nplurals=10; plural=0;") == 10
    with pytest.raises(ValueError, match="no language has 11 plural forms"):
        nplurals_from_header("nplurals=11; plural=0;")
