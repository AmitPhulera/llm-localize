import time

import pytest

from llm_localize.validation import find_problem, is_valid_translation


@pytest.mark.parametrize("source, translation", [
    ("Hello", "Hola"),
    ('Hello "world"', 'Hola "mundo"'),
    ("Hello \\n", "Hola \\n"),
    ("Hello %s", "Hola %s"),
    ("Hello %(name)s", "Hola %(name)s"),
    ("Hello {name}", "Hola {name}"),
    ("%(name)s has %(count)d", "%(count)d chez %(name)s"),  # named placeholders may move
    ("{0} and {1}", "{1} y {0}"),  # so may indexed ones
    ("%(count)02d files", "%(count)02d fichiers"),
    ("%.2f MB", "%.2f Mo"),
    ("100% sure", "100 % sûr"),  # a lone % isn't a placeholder
    ("Hi %(name)s, bye %(name)s", "Hola %(name)s"),  # named placeholders may repeat or not
    ("{0} and {0}", "{0}"),  # indexed placeholders may repeat or not
    ("Hello\nWorld", "Hola\nMundo"),
    ("Hello\nWorld", "Hola\n Mundo"),
    ("Hello &amp; World", "Hola &amp; Mundo"),
    ("Hello &amp; World", "Hola et Mundo"),
    ("  Hello  ", "  Hola  "),
    ("Hello {name}", "Hola {name}!"),
    ("%1$s sent %2$d files", "%2$d fichiers envoyés par %1$s"),  # numbered ones may move
    ("%@ has %lld items", "%@ a %lld éléments"),
    ("A 20%lift in sales", "Une hausse de 20 % des ventes"),  # not %li
    ("Up to 50%Sale", "Jusqu'à 50 % Soldes"),  # not Java's %S
    ("%ld/%lu", "%ld/%lu"),
])
def test_valid(source, translation):
    assert is_valid_translation(source, translation)


@pytest.mark.parametrize("source, translation", [
    ("Hello %(name)s", "Hola %(nombre)s"),
    ("Hello {name}", "Hola {nombre}"),
    ("Hello %s", "Hola"),
])
def test_invalid(source, translation):
    assert not is_valid_translation(source, translation)


@pytest.mark.parametrize("source, translation, reason", [
    ("Hello %(name)s", "Hola %(nombre)s", "placeholders"),
    ("%.2f MB", "MB", "placeholders"),
    ("%(count)02d files", "files", "placeholders"),
    ("%1$s sent %2$d files", "%1$s a envoyé des fichiers", "placeholders"),
    ("%@ has %lld items", "%@ a %d éléments", "placeholders"),
    # Java's date conversions and others, as Android strings use them
    ("Year: %1$tY", "Année : 2026", "placeholders"),
    ("Line%nbreak", "Ligne saut", "placeholders"),
    ("Active: %b", "Actif : oui", "placeholders"),
    ("Hello", "Hola", None),
])
def test_find_problem(source, translation, reason):
    assert find_problem(source, translation) == reason


def test_unclosed_named_placeholders_take_linear_time():
    started = time.perf_counter()
    find_problem("%(" * 100000, "%(" * 100000)
    assert time.perf_counter() - started < 1


def test_unmatched_braces_take_linear_time():
    started = time.perf_counter()
    find_problem("{" * 50000, "{" * 50000)
    assert time.perf_counter() - started < 0.5
