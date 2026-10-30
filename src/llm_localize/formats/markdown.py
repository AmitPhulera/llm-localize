"""Markdown documents, translated into a copy per language, like ``docs/fr/guide.md`` from ``docs/en/guide.md``."""


class _Unit:
    """A translatable block, and how to write its translation back: a prefix per line, and the line ending."""

    def __init__(self, key, text, first_prefix="", prefix="", suffix="", context=""):
        self.key, self.text, self.context = key, text, context
        self.first_prefix, self.prefix, self.suffix = first_prefix, prefix, suffix

    def render(self, translation):
        lines = translation.split("\n")
        return self.first_prefix + "\n".join(
            lines[:1] + [self.prefix + line if line else self.prefix.rstrip() for line in lines[1:]]
        ) + self.suffix


class _Parser:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.pieces = []
        self.index = 0

    def unit(self, text, first_prefix="", prefix="", suffix=""):
        if not text.strip():
            self.pieces.append(first_prefix + text + suffix)
            return
        self.pieces.append(_Unit(str(len(self.pieces)), text, first_prefix, prefix, suffix))

    def line(self, offset=0):
        index = self.index + offset
        return self.lines[index].rstrip("\r\n") if index < len(self.lines) else None

    def ending(self, index):
        line = self.lines[index]
        return line[len(line.rstrip("\r\n")):]
