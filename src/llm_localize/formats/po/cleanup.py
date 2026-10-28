"""Spot PO translations that would break ``compilemessages``."""
from llm_localize.validation import has_control_chars


def entry_has_control_chars(entry):
    """Like ``has_control_chars``, but for a whole PO entry, including each plural form."""
    if entry.msgid_plural:
        source = entry.msgid + entry.msgid_plural
        return any(has_control_chars(source, msgstr) for msgstr in entry.msgstr_plural.values())
    return has_control_chars(entry.msgid, entry.msgstr)
