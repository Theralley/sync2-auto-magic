"""Print UTF-16LE strings (min length 4) with file offsets; optional regex filter."""
import re
import sys

data = open(sys.argv[1], "rb").read()
flt = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", data):
    s = m.group().decode("utf-16le")
    if flt is None or flt.search(s):
        print(f"{m.start():8x} {s}")
