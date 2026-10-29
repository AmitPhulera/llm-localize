"""JSON translation files, one per language, as used by i18next, FormatJS, next-intl and vue-i18n.

Keys may nest: ``{"home": {"title": "Welcome"}}``. Plurals are read in
i18next's style, a key per CLDR category (``items_one``, ``items_other``),
and ICU messages like ``{count, plural, one {# item} other {# items}}``
are checked with the ICU rules.

Strings in arrays are translated too, with keys like ``weekdays[0]``,
through arrays and objects up to ``MAX_ARRAY_DEPTH`` levels inside one.
An array is translated as a whole, and written only once every string
in it is translated: until then the target lacks it, so the app falls
back to the source language rather than showing a gap. Other values,
like numbers, aren't translated, and a new target gets the source's.
"""
import json
import os
import re
from collections import Counter
from copy import deepcopy as copy_of
from functools import cached_property

from llm_localize import icu
from llm_localize.formats.base import load_json, write_file
from llm_localize.formats.monolingual import Message, MonolingualFile
from llm_localize.plurals import CATEGORIES, ordinal_categories

PLURAL_KEY_RE = re.compile(rf"^(.+)_({'|'.join(CATEGORIES)})$")
# An i18next reference to another key, like $t(common.save) or $t(key, {"count": 2})
NESTING_RE = re.compile(r"\$t\((?:[^()]|\([^()]*\))*\)")
# Levels of arrays and objects inside an array whose strings are translated; deeper ones are left alone
MAX_ARRAY_DEPTH = 10
# The most characters a file's keys may add up to, each string's key counted with those of the objects it's in
MAX_KEYS_SIZE = 20_000_000


class JsonFile(MonolingualFile):
    name = "json"
    extensions = (".json",)

    @property
    def instructions(self):
        return (
            "Messages come from a JSON translation file, e.g. for i18next or FormatJS, and each one's "
            "context gives its key. Keep {{name}} and {{- name}} interpolations, $t(...) references and "
            "ICU arguments like {name} or {count, number} exactly as they are. A message in ICU "
            "MessageFormat, like \"{count, plural, one {# file} other {# files}}\", must stay valid ICU: "
            "keep the argument names, any exact cases like =0 and every select case, translate only the "
            "text inside the cases, and give each plural argument one case per plural category of the "
            f"target language: {', '.join(self.plural_categories)}. In ICU messages an apostrophe "
            "before {, } or # starts quoted text, so write it twice: l''{app}, not l'{app}. Some "
            "values aren't text for people to read, like file formats (png), language or locale codes "
            "(en, fr-CA), identifiers, URLs and CSS classes: keep those exactly as they are."
        )

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
        grouped = _group_plurals(messages)
        if self.language and "zero" in self.plural_categories:
            # A language with a zero form gets items_zero from the plural, not as the plain override
            plurals = {_key(_plural_path(json.loads(key))) for key, message in grouped.items() if message.plurals}
            grouped = {key: message for key, message in grouped.items()
                       if not (key.endswith('_zero"]') and _key(_zero_base(json.loads(key))) in plurals)}
        return grouped

    @cached_property
    def target_messages(self):
        """The target's messages, keyed like the source's, with plurals grouped as the source groups them."""
        return self._messages_in({tuple(path): value for path, value in _strings(self.document)
                                  if _array_root(path) is None})

    def _messages_in(self, values):
        """Return the source's messages found in ``values``, ``{path: text}``, keyed and grouped like its own."""
        messages = {}
        for key, message in self.source_messages.items():
            path = _plural_path(json.loads(key))
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
        """The target's JSON; a new one starts with the source's numbers and other values that aren't text."""
        return _load(self.path) or _without_strings(self.source_document)

    @cached_property
    def _pending_arrays(self):
        """``{array path: (copy, keys left)}`` of arrays translated as a whole, kept out of the target until done.

        The keys left are the source's messages in the array not translated
        in the copy yet; it goes in the target when none are left.
        """
        return {}

    @cached_property
    def _array_messages(self):
        """``{array path: keys}`` of the source's messages in each array that need translating."""
        keys = {}
        for key, message in self.source_messages.items():
            root = _array_root(json.loads(key))
            if root is not None and not self.is_translated(message, None):
                keys.setdefault(root, set()).add(key)
        return keys

    def find_problem(self, source, translation):
        if Counter(NESTING_RE.findall(source)) != Counter(NESTING_RE.findall(translation)):
            return "placeholders"
        if icu.is_icu_choice(source):
            return icu.find_problem(source, translation, self.plural_categories, ordinal_categories(self.language))
        return super().find_problem(source, translation)

    def apply(self, key, translation):
        translation = self.with_translated_forms(key, translation)
        path = _plural_path(json.loads(key))
        root = _array_root(path)
        if root is None:
            _set(self.document, path, translation)
            return
        # A whole array: filled in a copy of the source's, which goes in the target once it's done
        if root not in self._pending_arrays:
            self._pending_arrays[root] = (_blank(_get(self.source_document, root)),
                                          set(self._array_messages.get(root, ())))
        array, left = self._pending_arrays[root]
        _set(array, path[len(root):], translation)
        left.discard(key)
        if not left:
            _set(self.document, root, self._pending_arrays.pop(root)[0])

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
    # An empty file, as an editor or touch makes, is a target with nothing in it yet
    if not text.strip():
        return {}
    document = load_json(text, path)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must hold a JSON object of messages")
    return document


def _without_strings(document):
    """Return a copy of nested objects without the text to translate, or objects left with nothing.

    Arrays with text are left out too: they're added once translated.

    >>> _without_strings({"a": "Hi", "b": ["x"], "c": {"d": "Bye", "e": 3}, "f": {"g": "Go"}, "h": [1, 2]})
    {'c': {'e': 3}, 'h': [1, 2]}
    """
    copy = {}
    for name, value in document.items():
        if isinstance(value, dict):
            value = _without_strings(value)
            if value:
                copy[name] = value
        elif isinstance(value, list):
            if not any(text.strip() for _, text in _array_strings(value, ())):
                copy[name] = copy_of(value)
        elif not isinstance(value, str):
            copy[name] = copy_of(value)
    return copy


def _strings(document, path=()):
    """Yield ``(path, text)`` for each string in nested objects and their arrays, in file order."""
    for name, value in document.items():
        if isinstance(value, str):
            yield [*path, name], value
        elif isinstance(value, dict):
            yield from _strings(value, (*path, name))
        elif isinstance(value, list):
            yield from _array_strings(value, (*path, name))


def _array_strings(value, path, depth=1):
    """Yield ``(path, text)`` for each string in an array, or an object in one, and those inside them.

    An element's path ends with its index. Only ``MAX_ARRAY_DEPTH`` levels
    are followed.

    >>> list(_array_strings(["a", 1, {"b": ["c"]}], ("x",)))
    [(['x', 0], 'a'), (['x', 2, 'b', 0], 'c')]
    """
    if depth > MAX_ARRAY_DEPTH:
        return
    for name, item in enumerate(value) if isinstance(value, list) else value.items():
        if isinstance(item, str):
            yield [*path, name], item
        elif isinstance(item, (list, dict)):
            yield from _array_strings(item, (*path, name), depth + 1)


def _blank(value, depth=1):
    """Return a copy of an array, or an object in one, without the strings ``_array_strings`` yields.

    An array keeps an empty string in each one's place, so the rest keep
    their indexes; an object leaves them out, as its plural keys depend
    on the target language.

    >>> _blank(["a", " ", 1, {"b": "c", "d": 2}])
    ['', ' ', 1, {'d': 2}]
    """
    if depth > MAX_ARRAY_DEPTH:
        return copy_of(value)
    copy = {}
    for name, item in enumerate(value) if isinstance(value, list) else value.items():
        if isinstance(item, str) and item.strip():
            if isinstance(value, list):
                copy[name] = ""
        else:
            copy[name] = _blank(item, depth + 1) if isinstance(item, (list, dict)) else item
    return list(copy.values()) if isinstance(value, list) else copy


def _shape(value):
    """Return a value's structure, to tell if two arrays line up: where arrays are, and their lengths.

    Strings in objects are found by their keys, so they needn't line up,
    and numbers and other values may differ.

    >>> _shape(["a", {"b": 2, "c": "x"}]) == _shape(["x", {"b": 3}]), _shape(["a"]) == _shape(["a", "b"])
    (True, False)
    """
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if isinstance(value, dict):
        return {name: _shape(item) for name, item in value.items() if not isinstance(item, str)}
    return type(value).__name__


def _array_root(path):
    """Return the path of the outermost array a path is in, or None.

    >>> _array_root(["faq", 0, "answer"]), _array_root(["home", "title"])
    (('faq',), None)
    """
    index = next((index for index, name in enumerate(path) if isinstance(name, int)), None)
    return None if index is None else tuple(path[:index])


def _get(document, path):
    """Return the value at ``path``, or None if there's none."""
    value = document
    for name in path:
        if isinstance(name, int) and isinstance(value, list) and name < len(value):
            value = value[name]
        elif isinstance(name, str) and isinstance(value, dict) and name in value:
            value = value[name]
        else:
            return None
    return value


def _set(document, path, value):
    """Set the value at ``path``, adding objects on the way; a dict of plural forms sets a key per category."""
    parent = document
    for index, name in enumerate(path[:-1]):
        # Arrays are always there already, as the source's copy or the target's own
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


def _plural_path(path):
    """Return a message's path in the file, without the ``null`` that marks a plural sharing a plain key's."""
    return path[:-1] if path and path[-1] is None else path


def _zero_base(path):
    """Return the plural path an ``items_zero`` path belongs to."""
    return [*path[:-1], path[-1][:-len("_zero")]]


def _context(path):
    """Return a message's context: its key, like ``home.title`` or ``faq[0].answer``."""
    key = ""
    for name in path:
        key += f"[{name}]" if isinstance(name, int) else f".{name}" if key else name
    return "Key: " + key


def _group_plurals(messages):
    """Merge i18next plural keys like ``items_one`` and ``items_other`` into one plural message ``items``.

    A key counts as plural when its object also has the ``_other`` key
    and at least one other category, so a lone ``show_other`` stays plain.
    ``items_zero`` stays plain too: i18next uses it for a count of 0 in
    any language, not as a CLDR category. A plural whose key an object
    also has as a plain string, like ``item`` beside ``item_one``, gets a
    ``null`` after its path, so the two keys differ.

    >>> grouped = _group_plurals({
    ...     '["items_one"]': Message("1 item"), '["items_other"]': Message("{{count}} items"),
    ...     '["show_other"]': Message("Show other"), '["items_zero"]': Message("No items"),
    ...     '["item"]': Message("Item"), '["item_one"]': Message("1 item"), '["item_other"]': Message("items"),
    ... })
    >>> {key: (m.text, m.plurals) for key, m in grouped.items()}  # doctest: +NORMALIZE_WHITESPACE
    {'["items"]': ('', {'one': '1 item', 'other': '{{count}} items'}), '["show_other"]': ('Show other', {}),
     '["items_zero"]': ('No items', {}), '["item"]': ('Item', {}),
     '["item", null]': ('', {'one': '1 item', 'other': 'items'})}
    """
    groups = {}
    for key in messages:
        path = json.loads(key)
        match = isinstance(path[-1], str) and PLURAL_KEY_RE.match(path[-1])
        if match and match.group(2) != "zero":
            base = [*path[:-1], match.group(1)]
            groups.setdefault(_key([*base, None] if _key(base) in messages else base), {})[match.group(2)] = key
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
            grouped[base_key] = Message(context=_context(_plural_path(json.loads(base_key))))
        category = PLURAL_KEY_RE.match(json.loads(key)[-1]).group(2)
        grouped[base_key].plurals[category] = message.text
    return grouped


def _ordered_like(value, source):
    """Return ``value`` with its objects' keys in the source's order, and keys only it has at the end."""
    if isinstance(value, list) and isinstance(source, list):
        return [_ordered_like(item, source[index]) if index < len(source) else item
                for index, item in enumerate(value)]
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
