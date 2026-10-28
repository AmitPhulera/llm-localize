"""Translate a file's untranslated units with an LLM, whatever the file format."""


def make_batches(units, batch_size):
    """Split units into batches keyed by position within the batch."""
    if batch_size < 1:
        raise ValueError(f"Batch size must be at least 1, not {batch_size}")
    return [
        {str(i): unit for i, unit in enumerate(units[start:start + batch_size])}
        for start in range(0, len(units), batch_size)
    ]
