"""Dump PE facts for a CE ARM DLL/EXE: header, imports (by DLL, with names/ordinals), exports."""
import sys
import json
import pefile


def info(path):
    pe = pefile.PE(path)
    fh = pe.FILE_HEADER
    oh = pe.OPTIONAL_HEADER
    out = {
        "path": path,
        "machine": hex(fh.Machine),
        "characteristics": hex(fh.Characteristics),
        "subsystem": oh.Subsystem,
        "subsystem_version": f"{oh.MajorSubsystemVersion}.{oh.MinorSubsystemVersion}",
        "os_version": f"{oh.MajorOperatingSystemVersion}.{oh.MinorOperatingSystemVersion}",
        "image_base": hex(oh.ImageBase),
        "size_of_image": oh.SizeOfImage,
        "entry": hex(oh.AddressOfEntryPoint),
        "sections": [(s.Name.rstrip(b"\0").decode(errors="replace"), hex(s.VirtualAddress), s.Misc_VirtualSize, s.SizeOfRawData, hex(s.Characteristics)) for s in pe.sections],
        "imports": {},
        "exports": [],
    }
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            names = []
            for imp in entry.imports:
                names.append(imp.name.decode() if imp.name else f"ord{imp.ordinal}")
            out["imports"][entry.dll.decode()] = names
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exp = pe.DIRECTORY_ENTRY_EXPORT
        out["export_dll_name"] = exp.name.decode() if exp.name else None
        out["export_base"] = exp.struct.Base
        for sym in exp.symbols:
            # data or code? check the section of the RVA
            sec = pe.get_section_by_rva(sym.address) if sym.address else None
            secname = sec.Name.rstrip(b"\0").decode() if sec else None
            out["exports"].append({"ord": sym.ordinal, "name": sym.name.decode() if sym.name else None,
                                   "rva": hex(sym.address), "section": secname,
                                   "forwarder": sym.forwarder.decode() if sym.forwarder else None})
    return out


if __name__ == "__main__":
    mode = sys.argv[1]
    for p in sys.argv[2:]:
        d = info(p)
        if mode == "json":
            print(json.dumps(d, indent=1))
        else:
            print("==", p)
            for k in ("machine", "characteristics", "subsystem", "subsystem_version", "os_version", "image_base", "size_of_image", "entry"):
                print(f"  {k}: {d[k]}")
            print("  sections:")
            for s in d["sections"]:
                print("    ", s)
            print("  imports:")
            for dll, names in d["imports"].items():
                print(f"    {dll}: {len(names)} -> {', '.join(names)}")
            print(f"  exports: {len(d['exports'])} (dll name {d.get('export_dll_name')}, base {d.get('export_base')})")
            if mode == "full":
                for e in d["exports"]:
                    print(f"    {e['ord']:5d} {e['name']} {e['rva']} {e['section']}")
