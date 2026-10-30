"""XLIFF 1.2 files, as written by Angular's extract-i18n and most translation tools."""
import os
from xml.parsers import expat

from llm_localize.formats.xml_utils import line_indent, tag_end, to_utf8


class _Segment:
    def __init__(self, context):
        self.context = context
        self.source = ""
        self.source_end = 0
        self.indent = b""
        self.target = None
        self.target_span = None
        self.target_inner = None
        self.state = None
        self.segment_tag = None


class _Parsed:
    def __init__(self, data):
        self.data = data
        self.encoding = None
        self.bom = b""
        self.version = "1"
        self.target_language = None
        self.segments = {}


def _read(path):
    if not os.path.exists(path):
        raise ValueError(f"{path} doesn't exist")
    with open(path, "rb") as f:
        data, encoding, bom = to_utf8(f.read(), path)
    parsed = _Parsed(data)
    parsed.encoding, parsed.bom = encoding, bom
    parser = expat.ParserCreate("UTF-8")
    stack = []  # (local name, attrs, start index, inner start)
    unit = {}

    def local(tag):
        return tag.rpartition(":")[2]

    def start(tag, attrs):
        name = local(tag)
        start_index = parser.CurrentByteIndex
        inner_start = tag_end(data, start_index)
        names = [entry[0] for entry in stack]
        if name == "xliff":
            parsed.version = "2" if attrs.get("version", "").startswith("2") else "1"
        elif name == "file" and attrs.get("target-language"):
            parsed.target_language = parsed.target_language or attrs["target-language"]
        elif name in ("trans-unit", "unit"):
            unit.clear()
            unit.update(id=attrs.get("id", ""), skip=attrs.get("translate") == "no", notes=[], segments=0,
                        state=None, segment_tag=None, read=[])
        elif name in ("source", "target") and _in_segment(names):
            if name == "source":
                unit["segments"] += 1
                key = f"{unit['id']}#{unit['segments']}" if parsed.version == "2" else unit["id"]
                if key in parsed.segments:
                    key = f"{key}#{len(parsed.segments)}"
                segment = _Segment(context="")
                segment.indent = line_indent(data, start_index)
                segment.segment_tag = unit["segment_tag"]
                segment.state = unit["state"]
                unit["current"] = None if unit["skip"] else (key, segment)
        stack.append((name, attrs, start_index, inner_start))

    def end(tag):
        name, attrs, start_index, inner_start = stack.pop()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{path} is not valid XML: {e}") from e
    return parsed


def _in_segment(names):
    """True if a source or target is a unit's own, not one inside alt-trans or a note."""
    return bool(names) and names[-1] in ("trans-unit", "segment")
