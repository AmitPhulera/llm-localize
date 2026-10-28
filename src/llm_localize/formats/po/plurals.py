"""Helpers for reading a PO file's ``Plural-Forms`` header."""
import gettext
import re

# Counts tried when working out which numbers each plural index is used for
PLURAL_SAMPLE_COUNTS = list(range(0, 201)) + [1000, 1000000, 2000000]

# More plural forms than any language has (Arabic has 6), so a header can't ask for thousands
MAX_NPLURALS = 10

# English-style rule used when a header has no ``plural=``: index 0 for
# exactly one, index 1 for every other count. Pairs with nplurals=2.
DEFAULT_PLURAL_EXPRESSION = "n != 1"


def nplurals_from_header(plural_forms_header):
    """Return the number of ``msgstr[N]`` indices a ``Plural-Forms`` header declares.

    Defaults to 2 (English-style singular and plural) when the header
    doesn't say.

    >>> nplurals_from_header("nplurals=3; plural=(n==1 ? 0 : n==2 ? 1 : 2);")
    3
    >>> nplurals_from_header("")
    2

    Raises ``ValueError`` for more than ``MAX_NPLURALS``.
    """
    match = re.search(r'nplurals\s*=\s*(\d+)', plural_forms_header)
    nplurals = int(match.group(1)) if match else 2
    if nplurals > MAX_NPLURALS:
        raise ValueError(f"Invalid Plural-Forms header {plural_forms_header!r}: no language has {nplurals} "
                         f"plural forms (at most {MAX_NPLURALS} are allowed)")
    return nplurals


def plural_index_function_from_header(plural_forms_header):
    """Return a function mapping a count ``n`` to the ``msgstr[N]`` index used for it.

    The ``plural=`` expression is written in C syntax, e.g.
    ``plural=(n%10==1 && n%100!=11 ? 0 : 1);``. ``gettext.c2py`` ("C to
    Python") is the standard library helper that ``ngettext`` itself uses
    to turn it into a Python function. It accepts only ``n``, numbers and
    operators, and raises ``ValueError`` for anything else.

    >>> plural_index_for = plural_index_function_from_header("nplurals=2; plural=(n != 1);")
    >>> plural_index_for(1), plural_index_for(5)
    (0, 1)
    """
    match = re.search(r'plural\s*=\s*([^;]+)', plural_forms_header)
    plural_expression = match.group(1) if match else DEFAULT_PLURAL_EXPRESSION
    return gettext.c2py(plural_expression)


def counts_by_plural_index_from_header(plural_forms_header):
    """Map each plural index to the sample counts that select it.

    >>> counts = counts_by_plural_index_from_header("nplurals=2; plural=(n != 1);")
    >>> counts[0], counts[1][:4]
    ([1], [0, 2, 3, 4])

    Raises ``ValueError`` when ``plural=`` picks an index that ``nplurals``
    doesn't allow, which msgfmt rejects too.
    """
    plural_index_for = plural_index_function_from_header(plural_forms_header)
    nplurals = nplurals_from_header(plural_forms_header)
    if nplurals < 1:
        raise ValueError(f"Invalid Plural-Forms header {plural_forms_header!r}: nplurals must be at least 1")
    counts = {plural_index: [] for plural_index in range(nplurals)}
    for n in PLURAL_SAMPLE_COUNTS:
        try:
            index = plural_index_for(n)
        except ZeroDivisionError as e:
            raise ValueError(
                f"Invalid Plural-Forms header {plural_forms_header!r}: plural= divides by zero") from e
        if index not in counts:
            raise ValueError(
                f"Inconsistent Plural-Forms header {plural_forms_header!r}: "
                f"nplurals is {nplurals}, but plural= gives index {index} for n={n}")
        counts[index].append(n)
    return counts
