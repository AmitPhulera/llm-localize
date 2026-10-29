"""JSON translation files, one per language, as used by i18next, FormatJS, next-intl and vue-i18n.

Keys may nest: ``{"home": {"title": "Welcome"}}``.
"""
import json
import os
import re
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile

# The most characters a file's keys may add up to, each string's key counted with those of the objects it's in
MAX_KEYS_SIZE = 20_000_000


class JsonFile(MonolingualFile):
    name = "json"
    extensions = (".json",)

    def read_messages(self, path):
        messages, size = {}, 0
        for path_in_file, value in _strings(_load(path)):
            key = _key(path_in_file)
            # Each string's key holds the keys of every object it's in, so a small file of long keys nested
            # deep could otherwise take gigabytes
            size += len(key)
            if size > MAX_KEYS_SIZE:
                raise ValueError(f"{path} has too much key text: its strings' keys, each with the keys of the "
                                 f"objects it's in, add up to over {MAX_KEYS_SIZE:,} characters")
            messages[key] = Message(text=value, context=_context(path_in_file))
        return messages

    @cached_property
    def source_document(self):
        return _load(self.source_path)

    @cached_property
    def document(self):
        return _load(self.path)

    def apply(self, key, translation):
        path = json.loads(key)
        _set(self.document, path, translation)

    @cached_property
    def _save_style(self):
        """The target's indentation and ending, or the source's for a new or empty target; read once."""
        return _style(self.path) if _load(self.path) else _style(self.source_path)

    def save(self):
        style = self._save_style
        document = _ordered_like(self.document, self.source_document)
        text = json.dumps(document, ensure_ascii=False, indent=style["indent"])
        write_file(self.path, (text + style["end"]).encode())


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


def _ordered_like(value, source):
    """Return ``value`` with its objects' keys in the source's order, and keys only it has at the end."""
    if not (isinstance(value, dict) and isinstance(source, dict)):
        return value
    order = {name: index for index, name in enumerate(source)}
    return {name: _ordered_like(value[name], source.get(name))
            for name in sorted(value, key=lambda name: _source_position(name, order))}


def _source_position(name, order):
    """Sort a key by the source's position, putting keys it lacks at the end."""
    if name in order:
        return order[name]
    return len(order)


def _style(path):
    """Return the file's indentation and ending, so a save keeps them."""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    match = re.search(r"^\{\s*?\n([ \t]+)\S", text)
    return {"indent": match.group(1) if match else None, "end": "\n" if text.endswith("\n") else ""}
