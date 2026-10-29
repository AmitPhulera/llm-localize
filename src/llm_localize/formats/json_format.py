"""JSON translation files, one per language, as used by i18next, FormatJS, next-intl and vue-i18n.

Keys may nest: ``{"home": {"title": "Welcome"}}``.
"""
import json
import os


def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    return json.loads(text)


def _strings(document, path=()):
    """Yield ``(path, text)`` for each string in nested objects, in file order."""
    for name, value in document.items():
        if isinstance(value, str):
            yield [*path, name], value
        elif isinstance(value, dict):
            yield from _strings(value, (*path, name))


def _set(document, path, value):
    """Set the value at ``path``, adding objects on the way."""
    parent = document
    for index, name in enumerate(path[:-1]):
        if isinstance(name, str) and not isinstance(parent.get(name), list if isinstance(path[index + 1], int)
                                                    else dict):
            parent[name] = {}
        parent = parent[name]
    parent[path[-1]] = value


def _key(path):
    """Return the unit key for a path of object keys: the path as JSON, since keys may hold dots."""
    return json.dumps(list(path), ensure_ascii=False)


def _context(path):
    """Return a message's context: its key, like ``home.title``."""
    key = ""
    for name in path:
        key += f"[{name}]" if isinstance(name, int) else f".{name}" if key else name
    return "Key: " + key
