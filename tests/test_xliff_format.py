from random import Random

from llm_localize.formats.xml_utils import line_indent


def test_line_indent_matches_scanning_the_whole_line():
    def scanned(data, start):
        line = data[data.rfind(b"\n", 0, start) + 1:start]
        return line if line.isspace() else b""

    random = Random(0)
    for _ in range(2000):
        data = bytes(random.choice(b" \t\n\r\x0bx<") for _ in range(random.randrange(12)))
        for start in range(len(data) + 1):
            assert line_indent(data, start) == scanned(data, start), (data, start)
