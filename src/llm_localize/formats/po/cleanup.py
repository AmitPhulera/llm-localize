"""Spot and blank PO translations that would break ``compilemessages``."""
import bisect
import logging
import os
import re
import shutil
import subprocess
import tempfile

import polib

from llm_localize.validation import has_control_chars

logger = logging.getLogger(__name__)

# msgfmt errors look like "<file>.po:<line>: <message>"
MSGFMT_ERROR_RE = re.compile(r'^.+\.po:(\d+):\s*(.*)$')


def entry_has_control_chars(entry):
    """Like ``has_control_chars``, but for a whole PO entry, including each plural form."""
    if entry.msgid_plural:
        source = entry.msgid + entry.msgid_plural
        return any(has_control_chars(source, msgstr) for msgstr in entry.msgstr_plural.values())
    return has_control_chars(entry.msgid, entry.msgstr)


def save_po(po):
    """Save ``po`` over its file only once it is fully written, so a failure leaves the file as it was."""
    # Through any symlink, so the link stays a link to the updated file
    path = os.path.realpath(po.fpath)
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.po.tmp')
    os.close(fd)
    try:
        po.save(temp_path)
        shutil.copymode(path, temp_path)
        os.replace(temp_path, path)
    except BaseException:
        os.unlink(temp_path)
        raise


def run_msgfmt(file_path):
    """Run ``msgfmt --check`` and return the ``subprocess.CompletedProcess``."""
    result = subprocess.run(
        ['msgfmt', '--check', '-o', os.devnull, str(file_path)],
        # Untranslated output, so warnings say "warning" and aren't taken for errors
        env={**os.environ, 'LC_ALL': 'C'},
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def extract_errored_line_numbers(error_output, file_path=None):
    """Map line number to error message for each ``msgfmt`` error, skipping warnings.

    With ``file_path``, only errors in that file count, whatever its name ends
    with, as a PO file read with ``--format po`` may be called anything.

    >>> extract_errored_line_numbers("x.po:3: bad\\nx.po:5: warning: meh\\nx.po: warning: no line")
    {3: 'bad'}
    >>> extract_errored_line_numbers("up.txt:3: bad", "up.txt")
    {3: 'bad'}

    A line starting with "..." continues the error before it, like the
    "...this is the location of the first definition" after a duplicate.
    """
    pattern = re.compile(re.escape(str(file_path)) + r":(\d+):\s*(.*)$") if file_path else MSGFMT_ERROR_RE
    line_num_error_map = {}
    for line in error_output.splitlines():
        # Only trust lines that point at a PO file line. Anything else, like
        # lines without a line number ("<file>: warning: Charset missing in
        # header.") or stray output from native libraries in the subprocess
        # ("…/driver.rs:196:23: …"), must not map to a msgstr.
        match = pattern.match(line)
        if not match:
            continue
        line_num, message = match.groups()
        if message.startswith(('warning', '...')):
            continue
        line_num_error_map[int(line_num)] = message.strip()
    return line_num_error_map


def clear_translations_at_lines(file_path, line_num_error_map):
    """Blank the entries whose span contains an errored line and return how many were cleared.

    ``polib`` only records the line each entry starts on, so an errored
    line belongs to the last entry starting on or before it.
    """
    po = polib.pofile(file_path)
    entries = sorted(po, key=lambda entry: entry.linenum)
    starts = [entry.linenum for entry in entries]
    cleared = set()
    for line_num in sorted(line_num_error_map):
        index = _index_of_entry_at(starts, line_num)
        if index is None:
            logger.warning("No entry found for msgfmt error at line %d: %s",
                           line_num, line_num_error_map[line_num])
            continue
        entry = entries[index]
        if id(entry) in cleared:
            continue
        logger.info(
            "Removing translation with msgfmt error: %s\n  msgid: %s (line %d)\n  msgstr: %s",
            line_num_error_map[line_num], entry.msgid, entry.linenum,
            entry.msgstr_plural if entry.msgid_plural else entry.msgstr,
        )
        _clear(entry)
        cleared.add(id(entry))
    if cleared:
        save_po(po)
        logger.info("Removed %d translations with msgfmt errors from %s", len(cleared), file_path)
    return len(cleared)


def _index_of_entry_at(starts, line_num):
    """Return the index of the last start on or before ``line_num``, or None.

    >>> _index_of_entry_at([10, 20, 30], 20), _index_of_entry_at([10, 20, 30], 25), _index_of_entry_at([10], 5)
    (1, 1, None)
    """
    return bisect.bisect_right(starts, line_num) - 1 if starts and starts[0] <= line_num else None


def _clear(entry):
    if entry.msgid_plural:
        # Plural entries store their translations in msgstr_plural, not
        # msgstr, so blank every msgstr[N] to actually clear it.
        entry.msgstr_plural = {k: "" for k in entry.msgstr_plural}
    else:
        entry.msgstr = ""
