"""Turn an akprof hist=PATH dump into a per-function profile.

usage: profile.py HIST (--nm FILE.nm | --pe DLL) [--top N]

--nm  uses the full symbol table of an unstripped build (static functions included).
--pe  uses only the DLL's export table (stock DLLs): static functions are then charged to
      the nearest exported symbol below them, so that profile is approximate.
"""
import bisect
import collections
import sys

args = sys.argv[1:]
hist, nm, pe_path, top = args[0], None, None, 25
i = 1
while i < len(args):
    if args[i] == "--nm":
        nm = args[i + 1]; i += 2
    elif args[i] == "--pe":
        pe_path = args[i + 1]; i += 2
    elif args[i] == "--top":
        top = int(args[i + 1]); i += 2
    else:
        sys.exit(f"bad arg {args[i]}")

syms = []
if nm:
    for line in open(nm):
        p = line.split()
        if len(p) == 3 and p[1] in "tT":
            syms.append((int(p[0], 16), p[2]))
else:
    import pefile
    pe = pefile.PE(pe_path)
    base = pe.OPTIONAL_HEADER.ImageBase
    syms = [(base + e.address, e.name.decode()) for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name]
syms.sort()
addrs = [a for a, _ in syms]

per = collections.Counter()
total = 0
for line in open(hist):
    a, c = line.split()
    a, c = int(a, 16), int(c)
    total += c
    j = bisect.bisect_right(addrs, a) - 1
    per[syms[j][1] if j >= 0 else "?"] += c

print(f"total {total} instructions in range ({'exports only, approximate' if pe_path else 'full symbols'})")
cum = 0
for name, c in per.most_common(top):
    cum += c
    print(f"{100.0 * c / total:6.2f}%  {100.0 * cum / total:6.2f}%  {c:14d}  {name}")
