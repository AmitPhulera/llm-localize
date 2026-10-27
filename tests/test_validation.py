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
    ("<a>Hello</a>", "<a>Hola</a>"),
    ('<a href="test">Hello</a>', '<a href="test">Hola</a>'),
    ("%(name)s has %(count)d", "%(count)d chez %(name)s"),  # named placeholders may move
    ("{0} and {1}", "{1} y {0}"),  # so may indexed ones
    ("%(count)02d files", "%(count)02d fichiers"),
    ("%.2f MB", "%.2f Mo"),
    ("100% sure", "100 % sûr"),  # a lone % isn't a placeholder
    ("Hi %(name)s, bye %(name)s", "Hola %(name)s"),  # named placeholders may repeat or not
    ("{} and {}", "{} y {}"),
    ("{0} and {0}", "{0}"),  # indexed placeholders may repeat or not
    ("<br/>", "<br/>"),
    ("Hello\nWorld", "Hola\nMundo"),
    ("Hello\nWorld", "Hola\n Mundo"),
    ("Hello &amp; World", "Hola &amp; Mundo"),
    ("Hello &amp; World", "Hola et Mundo"),
    ("  Hello  ", "  Hola  "),
    ("Hello {name}", "Hola {name}!"),
    ("Open { to start", "Ouvrez { pour commencer"),  # not a format string
    ("Press <b>Enter</b>", "Appuyez sur <B>Entrée</B>"),  # tag names aren't case-sensitive
    ("%1$s sent %2$d files", "%2$d fichiers envoyés par %1$s"),  # numbered ones may move
    ("%@ has %lld items", "%@ a %lld éléments"),
    ("A 20%lift in sales", "Une hausse de 20 % des ventes"),  # not %li
    ("Up to 50%Sale", "Jusqu'à 50 % Soldes"),  # not Java's %S
    ("%ld/%lu", "%ld/%lu"),
    ("<style>p {}</style>Hi", "<style>p {}</style>Salut"),
    ("<textarea>Type here</textarea>", "<textarea>Escriba aquí</textarea>"),  # text, unlike a script
    ("<title>Home</title>", "<title>Inicio</title>"),
])
def test_valid(source, translation):
    assert is_valid_translation(source, translation)


@pytest.mark.parametrize("source, translation", [
    ("Hello %(name)s", "Hola %(nombre)s"),
    ("Hello {name}", "Hola {nombre}"),
    ("Hello %s", "Hola"),
    ("<a>Hello</a>", "<b>Hola</b>"),
    ("<a>Hello</a>", "<a>Hola"),
    ("<a>Hello</a>", "Hola"),
    ("<a>Hello</a><b>x</b>", "<b>x</b><a>Hola</a>"),  # tag order changed
])
def test_invalid(source, translation):
    assert not is_valid_translation(source, translation)


@pytest.mark.parametrize("source, translation, reason", [
    ("Hello %(name)s", "Hola %(nombre)s", "placeholders"),
    ("%s of %s", "%s", "placeholders"),
    ("%.2f MB", "MB", "placeholders"),
    ("%(count)02d files", "files", "placeholders"),
    ("{} and {}", "{}", "placeholders"),
    ("<a>Hello</a>", "<b>Hola</b>", "HTML tags"),
    ("<a>Hello</a>", "Hola", "HTML tags"),
    ("Hello {name}", "Hola {name}}", "placeholders"),  # no longer a valid format string
    ("{count} items", "{count} éléments {", "placeholders"),
    ("Hello", "Hola <img/src=x onerror=alert(1)>", "HTML tags"),
    ("Hello", "Hola <svg/onload=alert(1)>", "HTML tags"),
    ("<b>Hi</b>", "<b>Hola</b><img\nsrc=x onerror=alert(1)>", "HTML tags"),
    ("Name: %s, count: %d", "Compte : %d, nom : %s", "placeholders"),  # unnamed ones can't move
    ("{} of {:.2f}", "{:.2f} de {}", "placeholders"),
    ("%1$s sent %2$d files", "%1$s a envoyé des fichiers", "placeholders"),
    ("%@ has %lld items", "%lld éléments pour %@", "placeholders"),
    ("%@ has %lld items", "%@ a %d éléments", "placeholders"),
    # Java's date conversions and others, as Android strings use them
    ("Year: %1$tY", "Année : 2026", "placeholders"),
    ("Line%nbreak", "Ligne saut", "placeholders"),
    ("Active: %b", "Actif : oui", "placeholders"),
    # Markup a browser would read on, left unfinished or hidden in a comment or CDATA
    ("Hello", "Bonjour <img src=x onerror=alert(document.cookie)//", "HTML tags"),
    ("<b>Hello</b>", "<b>Bonjour</b> <a href=//evil.example onclick=alert(1)//", "HTML tags"),
    ("Save", "Sauvegarder <!--", "HTML tags"),
    ("Save", "Sauvegarder <!-- hidden -->", "HTML tags"),
    ("Save", "Sauvegarder <![CDATA[x]]>", "HTML tags"),
    ("Save", "Sauvegarder <?php echo 1 ?>", "HTML tags"),
    # Markup in SVG's <style>, which browsers parse, unlike HTML's
    ("<svg><style>/* x */</style></svg>", "<svg><style><img src=x onerror=alert(1)></style></svg>", "HTML tags"),
    ("<svg><script>safe()</script></svg>", "<svg><script>alert(document.cookie)</script></svg>", "HTML tags"),
    ("<svg><script><![CDATA[go()]]></script></svg>", "<svg><script><![CDATA[bad()]]></script></svg>", "HTML tags"),
    # Script and style content is code
    ("Hi <script></script>", "Salut <script>alert(document.cookie)</script>", "HTML tags"),
    ("Hi <script></script>", "Salut <script/>alert(document.cookie)</script>", "HTML tags"),  # not self-closing
    ("<style>@import 'site.css';</style>Hi", "<style>@import 'evil.css';</style>Salut", "HTML tags"),
    ("Hello", "Hola", None),
])
def test_find_problem(source, translation, reason):
    assert find_problem(source, translation) == reason


def test_unclosed_named_placeholders_take_linear_time():
    started = time.perf_counter()
    find_problem("%(" * 100000, "%(" * 100000)
    assert time.perf_counter() - started < 1


def test_unfinished_cdata_sections_take_linear_time():
    started = time.perf_counter()
    assert find_problem("<![CDATA[" * 100000, "x") == "HTML tags"
    # Left unfinished, it's compared as it is: a browser would read what follows a > in it
    assert find_problem("Start with <![CDATA[ and close it", "Commencez par <![CDATA[> <img src=x onerror=f()>") \
        is not None
    assert time.perf_counter() - started < 1


@pytest.mark.parametrize("translation, reason", [
    ("Bonjour <3>{{name}}</3>, lisez <1>les conditions</1>.", None),  # word order may move them
    ("Bonjour <2>{{name}}</2>, lisez <5>les conditions</5>.", "HTML tags"),
    ("Bonjour {{name}}</1>, lisez les conditions</3>.", "HTML tags"),
])
def test_numbered_tags_are_kept(translation, reason):
    assert find_problem("Hello <1>{{name}}</1>, read <3>the terms</3>.", translation) == reason


def test_unmatched_braces_take_linear_time():
    started = time.perf_counter()
    find_problem("{" * 50000, "{" * 50000)
    assert time.perf_counter() - started < 0.5
