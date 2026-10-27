"""Checks that catch LLM translations likely to break placeholders."""
import re

# Finds %-style placeholders, with optional name or position, flags, width,
# precision and length (%s, %(name)s, %.2f, %(count)02d, Android's %1$s
# and Java's %1$tY, %b, %n, %,d and %<s, iOS's %@ and %lld), and {}-style ones
# ({}, {name}, {:.2f}). The space
# flag is left out: it would turn "100% sure" into a placeholder, and a
# length modifier followed by a word ("a 20%lift") isn't one either. So is
# Java's ( flag, which would make "5%(approx)" one.
PLACEHOLDER_RE = re.compile(
    r'%(?:\([^)%]+\)|\d+\$)?[-+0#,]*(?:\*|\d+)?(?:\.(?:\*|\d+))?'
    r'(?:(?:hh|h|ll|l|q|z|t|j|L)[diouxXeEfFgGcrsa@](?![A-Za-z])'
    r'|[tT][HIklMSLNpzZsQBbhAaCYyjmdeRTrDFc](?![A-Za-z])|[bBhHSC](?![A-Za-z])|[diouxXeEfFgGcrsa%@n])'
    # Java's %<s, the argument before it again; not "50%<b>", a number before a tag
    r'|%<[-+0#,]*\d*(?:\.\d+)?(?:[tT][HIklMSLNpzZsQBbhAaCYyjmdeRTrDFc]|[bBhHSCcdoxXeEfgGaAs])(?![A-Za-z>/])'
    r'|{(?:[^{}]|{[^{}]*})*}')


def find_problem(source, translation):
    """Return why ``translation`` is unsafe for ``source``, or None if it looks fine.

    The reason is ``"placeholders"``.

    >>> find_problem("Hello %(name)s", "Hola %(nombre)s")
    'placeholders'
    >>> find_problem("Hello %(name)s", "Hola %(name)s") is None
    True
    """
    source_placeholders = PLACEHOLDER_RE.findall(source)
    translation_placeholders = PLACEHOLDER_RE.findall(translation)
    if set(source_placeholders) != set(translation_placeholders):
        return "placeholders"
    return None


def is_valid_translation(source, translation):
    """Return True if ``translation`` is likely a safe translation of ``source``."""
    return find_problem(source, translation) is None
