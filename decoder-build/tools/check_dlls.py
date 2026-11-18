"""Check a set of built FFmpeg CE DLLs against the stock ones and AutoKit's needs.

usage: check_dlls.py <built_bin_dir> <stock_dir> [s2am_native_dir]

Checks:
  * PE: machine ARM (0x1C0), subsystem 9 (Windows CE GUI), DLL flag, .reloc present
  * every import name exists in an allow-list = names imported by the stock FFmpeg DLLs,
    any other PE in the stock AutoKit folder, and the s2am native programs (all of which
    load on the car); names outside that list are reported for a manual check against the
    CE 6.0 coredll.def
  * the 16 functions AutoKit resolves with GetProcAddress are exported by the right DLL
  * which stock exports are missing (informational: only AutoKit loads these DLLs)
Exit code 1 if a hard check fails.
"""
import glob
import os
import re
import sys

import pefile

AUTOKIT_NEEDS = {
    "avcodec-56.dll": ["avcodec_register_all", "avcodec_open2", "av_parser_init",
                       "avcodec_find_decoder", "av_free_packet", "av_init_packet",
                       "avcodec_alloc_context3", "avcodec_close", "avcodec_decode_video2",
                       "av_parser_parse2", "av_parser_close"],
    "avutil-54.dll": ["av_frame_alloc", "av_frame_free", "av_free", "av_malloc"],
    "avformat-56.dll": ["av_register_all"],
}
OWN = {"avcodec-56.dll", "avutil-54.dll", "avformat-56.dll"}


def load(path):
    pe = pefile.PE(path)
    imports = {}
    for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        names = imports.setdefault(e.dll.decode().lower(), set())
        for i in e.imports:
            names.add(i.name.decode() if i.name else f"#{i.ordinal}")
    exports = set()
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exports = {s.name.decode() for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name}
    return pe, imports, exports


def main():
    built, stock = sys.argv[1], sys.argv[2]
    extra = sys.argv[3] if len(sys.argv) > 3 else None
    allowed = {}
    sources = glob.glob(os.path.join(stock, "*.dll")) + glob.glob(os.path.join(stock, "*.DLL")) \
        + glob.glob(os.path.join(stock, "*.exe"))
    if extra:
        sources += glob.glob(os.path.join(extra, "*.exe"))
    for f in sources:
        try:
            _, imps, _ = load(f)
        except pefile.PEFormatError:
            continue
        for dll, names in imps.items():
            if dll.startswith("coredll"):
                for n in names:
                    allowed.setdefault(n, set()).add(os.path.basename(f))
    ok = True
    for name in sorted(OWN):
        path = os.path.join(built, name)
        pe, imps, exps = load(path)
        fh, oh = pe.FILE_HEADER, pe.OPTIONAL_HEADER
        print(f"== {name}  size {os.path.getsize(path)}  (stock {os.path.getsize(os.path.join(stock, name))})")
        hard = []
        if fh.Machine != 0x1C0:
            hard.append(f"machine {fh.Machine:#x} != 0x1c0 (ARM)")
        if oh.Subsystem != 9:
            hard.append(f"subsystem {oh.Subsystem} != 9 (Windows CE GUI)")
        if not fh.Characteristics & 0x2000:
            hard.append("not a DLL")
        if not oh.DATA_DIRECTORY[5].Size:
            hard.append("no base relocations")
        if oh.DATA_DIRECTORY[9].Size:
            hard.append("has a TLS directory")
        print(f"   machine {fh.Machine:#x}, subsystem {oh.Subsystem} v{oh.MajorSubsystemVersion}.{oh.MinorSubsystemVersion},"
              f" DLL {bool(fh.Characteristics & 0x2000)}, relocs {oh.DATA_DIRECTORY[5].Size} B,"
              f" TLS {oh.DATA_DIRECTORY[9].Size}, DllCharacteristics {oh.DllCharacteristics:#x}")
        for dll, names in sorted(imps.items()):
            if dll.startswith("coredll"):
                unknown = sorted(n for n in names if n not in allowed)
                print(f"   imports {dll}: {len(names)} names; not seen in any car-proven binary: {unknown or 'none'}")
                if unknown:
                    hard.append(f"unproven COREDLL imports {unknown}")
            elif dll in OWN:
                _, _, target_exports = load(os.path.join(built, dll))
                missing = sorted(names - target_exports)
                print(f"   imports {dll}: {len(names)} names; unresolved against built {dll}: {missing or 'none'}")
                if missing:
                    hard.append(f"unresolved imports from {dll}: {missing}")
            else:
                hard.append(f"imports unexpected DLL {dll}")
                print(f"   imports {dll}: {sorted(names)}  <-- UNEXPECTED")
        need = AUTOKIT_NEEDS[name]
        missing = [n for n in need if n not in exps]
        print(f"   AutoKit needs {len(need)}: {'all exported' if not missing else 'MISSING ' + str(missing)}")
        if missing:
            hard.append(f"missing AutoKit exports {missing}")
        _, _, stock_exps = load(os.path.join(stock, name))
        gone = sorted(stock_exps - exps)
        public = [n for n in gone if not n.startswith(("ff_", "avpriv_"))]
        print(f"   exports {len(exps)} (stock {len(stock_exps)}); stock exports absent: {len(gone)}"
              f" ({len(public)} public av*/other)")
        if "-v" in sys.argv:
            print("     ", ", ".join(public))
        for h in hard:
            print("   FAIL:", h)
        ok &= not hard
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
