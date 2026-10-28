"""Spot PO translations that would break ``compilemessages``."""
import os
import shutil
import tempfile

from llm_localize.validation import has_control_chars


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
