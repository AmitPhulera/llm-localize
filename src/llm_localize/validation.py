"""Checks that catch LLM translations likely to break placeholders."""
import re
import string

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
    # Named placeholders may be used any number of times, in any order, but
    # each positional one consumes the next argument, so they must match in order
    if _positional(source_placeholders) != _positional(translation_placeholders):
        return "placeholders"
    # A brace format string must stay one, e.g. "{name}" mustn't become "{name}}"
    if _is_brace_format(source) and not _is_brace_format(translation):
        return "placeholders"
    return None


def is_valid_translation(source, translation):
    """Return True if ``translation`` is likely a safe translation of ``source``."""
    return find_problem(source, translation) is None


def _positional(placeholders):
    """List the placeholders that take the next argument, in order: unnamed %-style ones, then ``{}``-style ones.

    The two styles are listed apart, since a string is formatted with one or the other.
    Numbered ones like ``%1$s`` name their argument, so they aren't listed.

    >>> _positional(["%s", "%(name)s", "%%", "{}", "{:.2f}", "{0}", "{name}", "%d", "%1$s", "%@"])
    (['%s', '%d', '%@'], ['{}', '{:.2f}'])
    """
    return (
        [p for p in placeholders if p.startswith("%") and not p.startswith("%(") and p != "%%" and "$" not in p],
        [p for p in placeholders if p.startswith("{") and p[1:2] in ("}", ":", "!")],
    )


def _is_brace_format(text):
    """Return True if ``text`` has ``{}``-style fields and ``str.format`` can parse it.

    >>> _is_brace_format("Hi {name}"), _is_brace_format("Hi {name}}"), _is_brace_format("Hi")
    (True, False, False)
    """
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        return False
    return any(field is not None for _, field, _, _ in parsed)
