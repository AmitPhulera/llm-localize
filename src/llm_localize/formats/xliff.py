"""XLIFF 1.2 files, as written by Angular's extract-i18n and most translation tools."""
import os
from xml.parsers import expat

from llm_localize.formats.xml_utils import tag_end, to_utf8


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

    def local(tag):
        return tag.rpartition(":")[2]

    def start(tag, attrs):
        name = local(tag)
        start_index = parser.CurrentByteIndex
        inner_start = tag_end(data, start_index)
        if name == "xliff":
            parsed.version = "2" if attrs.get("version", "").startswith("2") else "1"
        elif name == "file" and attrs.get("target-language"):
            parsed.target_language = parsed.target_language or attrs["target-language"]
        stack.append((name, attrs, start_index, inner_start))

    parser.StartElementHandler = start
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise ValueError(f"{path} is not valid XML: {e}") from e
    return parsed
