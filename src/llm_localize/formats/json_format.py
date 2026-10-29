"""JSON translation files, one per language, as used by i18next, FormatJS, next-intl and vue-i18n.

Keys may nest: ``{"home": {"title": "Welcome"}}``. Plurals are read in
i18next's style, a key per CLDR category (``items_one``, ``items_other``).
"""
import json
import os
import re
from functools import cached_property

from llm_localize.formats.base import write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.plurals import CATEGORIES

PLURAL_KEY_RE = re.compile(rf"^(.+)_({'|'.join(CATEGORIES)})$")
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
        return _group_plurals(messages)

    @cached_property
    def target_messages(self):
        """The target's messages, keyed like the source's, with plurals grouped as the source groups them."""
        return self._messages_in({tuple(path): value for path, value in _strings(self.document)})

    def _messages_in(self, values):
        """Return the source's messages found in ``values``, ``{path: text}``, keyed and grouped like its own."""
        messages = {}
        for key, message in self.source_messages.items():
            path = json.loads(key)
            if message.plurals:
                forms = {category: values.get((*path[:-1], f"{path[-1]}_{category}")) for category in CATEGORIES}
                messages[key] = Message(plurals={category: text for category, text in forms.items() if text})
            elif tuple(path) in values:
                messages[key] = Message(text=values[tuple(path)])
        return messages

    @cached_property
    def source_document(self):
        return _load(self.source_path)

    @cached_property
    def document(self):
        return _load(self.path)

    def apply(self, key, translation):
        translation = self.with_translated_forms(key, translation)
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
    """Set the value at ``path``, adding objects on the way; a dict of plural forms sets a key per category."""
    parent = document
    for index, name in enumerate(path[:-1]):
        if isinstance(name, str) and not isinstance(parent.get(name), list if isinstance(path[index + 1], int)
                                                    else dict):
            parent[name] = {}
        parent = parent[name]
    if isinstance(value, dict):
        for category, text in value.items():
            parent[f"{path[-1]}_{category}"] = text
    else:
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


def _group_plurals(messages):
    """Merge i18next plural keys like ``items_one`` and ``items_other`` into one plural message ``items``.

    A key counts as plural when its object also has the ``_other`` key
    and at least one other category, so a lone ``show_other`` stays plain.

    >>> grouped = _group_plurals({
    ...     '["items_one"]': Message("1 item"), '["items_other"]': Message("{{count}} items"),
    ...     '["show_other"]': Message("Show other"),
    ... })
    >>> {key: (m.text, m.plurals) for key, m in grouped.items()}
    {'["items"]': ('', {'one': '1 item', 'other': '{{count}} items'}), '["show_other"]': ('Show other', {})}
    """
    groups = {}
    for key in messages:
        path = json.loads(key)
        match = isinstance(path[-1], str) and PLURAL_KEY_RE.match(path[-1])
        if match:
            groups.setdefault(_key([*path[:-1], match.group(1)]), {})[match.group(2)] = key
    plural_keys = {}
    for base_key, keys in groups.items():
        if "other" in keys and len(keys) > 1:
            for key in keys.values():
                plural_keys[key] = base_key
    grouped = {}
    for key, message in messages.items():
        if key not in plural_keys:
            grouped[key] = message
            continue
        base_key = plural_keys[key]
        if base_key not in grouped:
            grouped[base_key] = Message(context=_context(json.loads(base_key)))
        category = PLURAL_KEY_RE.match(json.loads(key)[-1]).group(2)
        grouped[base_key].plurals[category] = message.text
    return grouped


def _ordered_like(value, source):
    """Return ``value`` with its objects' keys in the source's order, and keys only it has at the end."""
    if not (isinstance(value, dict) and isinstance(source, dict)):
        return value
    order = {name: index for index, name in enumerate(source)}
    return {name: _ordered_like(value[name], source.get(name))
            for name in sorted(value, key=lambda name: _source_position(name, order))}


def _source_position(name, order):
    """Sort a key by the source's position, putting plural keys where the source has any of theirs."""
    if name in order:
        return order[name]
    match = PLURAL_KEY_RE.match(name)
    if match:
        positions = [order[f"{match.group(1)}_{category}"] for category in CATEGORIES
                     if f"{match.group(1)}_{category}" in order]
        if positions:
            return min(positions) + CATEGORIES.index(match.group(2)) / 10
    return len(order)


def _style(path):
    """Return the file's indentation and ending, so a save keeps them."""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    match = re.search(r"^\{\s*?\n([ \t]+)\S", text)
    return {"indent": match.group(1) if match else None, "end": "\n" if text.endswith("\n") else ""}
