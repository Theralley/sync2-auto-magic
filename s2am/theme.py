"""Reversible colour themes for SYNC 2: Theme.XML and the four area gradients.

SYNC 2 takes each area's colours (phone top left, navigation top right, media bottom left,
climate bottom right) from ``\\8inchSkins\\Ford\\Sync\\Themes\\Theme.XML`` and the coloured
glow from ``yellow``/``green``/``red``/``blue.bmp`` (800x240) in the same folder. The car
also carries a complete Lincoln skin, which differs from Ford's in these five files and four
Flash screens (drive log, 2026-10-31).

A theme job checks that the car still has the files the Mac planned against, backs them up
on the car and onto the stick, copies the new ones in, and copies what it applied back to the
stick so the Mac can check every byte. SYNC restarts to load them. ``--restore`` copies the
originals back from the restore job itself (checked on the Mac), so it does not depend on the
backup on the car, which stays there for a manual restore. Ford's files stay in the Mac's store (``~/.s2am``); the job carries them
on the stick only.
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
import xml.etree.ElementTree as ElementTree
import zlib
from pathlib import Path

from .job import SCREENS, STARTUP_SCREENS
from .state import Store

THEMES_CE = "\\8inchSkins\\Ford\\Sync\\Themes"
FILES = ("Theme.XML", "yellow.bmp", "green.bmp", "red.bmp", "blue.bmp")
PRESETS = ("lincoln",)
COLOR = re.compile(r"0x[0-9a-fA-F]{6}")
ACTIVE = re.compile(rb"^[ \t]*<AppType [^>]*/>", re.MULTILINE)  # lines not inside <!-- -->
FETCH_LIMIT = (150, 64 * 1024 * 1024)  # files, bytes


class ThemeError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def whole_flash(data: bytes) -> bool:
    """A complete Flash file: FWS or CWS, and exactly as long as its header says."""
    if len(data) < 21 or data[:3] not in (b"FWS", b"CWS"):
        return False
    length = int.from_bytes(data[4:8], "little")
    if data[:3] == b"FWS":
        return length == len(data)
    try:
        return 8 + len(zlib.decompress(data[8:])) == length
    except zlib.error:
        return False


def latest_report_with(store: Store, serial: str, relative: str) -> Path | None:
    """The newest imported report that holds ``relative`` (a drive log's copy or list)."""
    for record in reversed(store.jobs(serial)):
        report = store.report(serial, record["id"])
        if report and (report / relative).is_file():
            return report
    return None


def originals(store: Store, serial: str) -> dict[str, bytes]:
    """The car's own five theme files, from the newest drive log that copied them."""
    folder = "skins/8inchSkins/Ford/Sync/Themes"
    report = latest_report_with(store, serial, f"{folder}/Theme.XML")
    if report is None:
        raise ThemeError("no copy of the car's theme files yet: run `s2am job logger --drive` first")
    return {name: (report / folder / name).read_bytes() for name in FILES}


def _app_types(xml: bytes) -> list[bytes]:
    return ACTIVE.findall(xml)


def check(name: str, new: bytes, old: bytes) -> None:
    """Refuse a file SYNC might not read: a theme must look like the one it replaces."""
    if name == "Theme.XML":
        try:
            root = ElementTree.fromstring(new)
        except ElementTree.ParseError as error:
            raise ThemeError(f"Theme.XML is not valid XML: {error}") from error
        types = root.findall("./Theme/System/AppTypes/AppType")
        if len(types) != len(_app_types(old)):
            raise ThemeError(f"Theme.XML has {len(types)} AppType entries; the car's has {len(_app_types(old))}")
        for app_type in types:
            for key in ("btnColor", "dialogColor", "dayColor", "nightColor"):
                if not COLOR.fullmatch(app_type.get(key, "")):
                    raise ThemeError(f"Theme.XML: {key}={app_type.get(key)!r} is not 0xRRGGBB")
        return
    if new[:2] != b"BM" or len(new) != len(old) or new[18:30] != old[18:30]:
        raise ThemeError(f"{name} must be a BMP of exactly the original's size and format "
                         f"({len(old)} bytes, 800x240, 24-bit)")


def lincoln(store: Store, serial: str) -> dict[str, bytes]:
    """Lincoln's colours on Ford's theme: its gradients, and its AppType colours in Ford's XML
    (the theme keeps its name, so nothing else about it changes)."""
    folder = "skins/8inchSkins/Lincoln/Sync/Themes"
    report = latest_report_with(store, serial, f"{folder}/Theme.XML")
    if report is None:
        raise ThemeError("no copy of the car's Lincoln skin yet: run `s2am job logger --drive` first")
    ford = originals(store, serial)["Theme.XML"]
    theirs = _app_types((report / folder / "Theme.XML").read_bytes())
    ours = _app_types(ford)
    if len(theirs) != len(ours):
        raise ThemeError("Ford's and Lincoln's Theme.XML differ in shape; not mixing them")
    pieces, last = [], 0
    for match, line in zip(ACTIVE.finditer(ford), theirs):
        pieces += [ford[last:match.start()], line]
        last = match.end()
    new = {"Theme.XML": b"".join(pieces) + ford[last:]}
    for name in FILES[1:]:
        new[name] = (report / folder / name).read_bytes()
    return new


def from_folder(source: Path) -> dict[str, bytes]:
    files = {name: (source / name).read_bytes() for name in FILES if (source / name).is_file()}
    if not files:
        raise ThemeError(f"{source} has none of {', '.join(FILES)}")
    return files


def fetch_list(store: Store, serial: str, patterns: list[str]) -> list[str]:
    """Car paths matching the patterns in the newest file list; read-only copies to the stick."""
    if not patterns:
        return []
    report = latest_report_with(store, serial, "files.txt")
    if report is None:
        raise ThemeError("no file list yet: run `s2am job logger --drive` first")
    wanted = [p.replace("/", "\\").lower() for p in patterns]
    found, total = [], 0
    for line in (report / "files.txt").read_text(errors="replace").splitlines():
        parts = line.split("|")
        if parts[0] != "F" or len(parts) < 3:
            continue
        path = parts[1]
        if '"' in path or path.lower().startswith("\\usb") or "?" in path:
            continue
        if any(fnmatch.fnmatchcase(path.lower(), p) for p in wanted):
            found.append(path)
            total += int(parts[2]) if parts[2].isdigit() else 0
    if not found:
        raise ThemeError(f"nothing on the car matches {patterns}")
    if len(found) > FETCH_LIMIT[0] or total > FETCH_LIMIT[1]:
        raise ThemeError(f"{len(found)} files, {total} bytes: too much to fetch at once")
    return found


def plan(store: Store, serial: str, preset: str | None, source: Path | None, restore: str | None,
         fetch: list[str]) -> tuple[dict, dict[str, bytes]]:
    """(job params, files for the job folder) for a theme job or its restore."""
    if restore:
        target = store.job(serial, restore)
        if target.get("kind") != "theme" or target["params"].get("restore"):
            raise ThemeError(f"{restore} is not a theme job")
        files = target["params"]["files"]
        old = originals(store, serial)  # the drive log's copy, checked against what the job replaced
        wrong = [n for n, f in files.items() if sha256(old[n]) != f["old_sha256"]]
        if wrong:
            raise ThemeError(f"the Mac's copy of {wrong} is not what {restore} replaced; not restoring it")
        return ({"restore": restore, "files": {n: f["old"] for n, f in files.items()},
                 "sha256": {n: f["old_sha256"] for n, f in files.items()},
                 "fetch": fetch_list(store, serial, fetch)},
                {f"orig-{n}": old[n] for n in files})
    if (preset is None) == (source is None):
        raise ThemeError("give either --preset or --from (or --restore JOB)")
    old = originals(store, serial)
    new = lincoln(store, serial) if preset == "lincoln" else from_folder(source)
    for name, data in new.items():
        check(name, data, old[name])
    changed = {name: data for name, data in new.items() if data != old[name]}
    if not changed:
        raise ThemeError("the new theme is the same as the car's; nothing to do")
    params = {
        "preset": preset, "fetch": fetch_list(store, serial, fetch),
        "files": {name: {"old": len(old[name]), "new": len(data), "old_sha256": sha256(old[name]),
                         "new_sha256": sha256(data)} for name, data in changed.items()},
    }
    extra = {f"new-{name}": data for name, data in changed.items()}
    extra["old-Theme.XML"] = old["Theme.XML"]  # the job compares the car's XML with this first
    return params, extra


MENU_FOLDER = "skins/8inchSkins/Ford/Sync/Apps/Info/SyncApps"
TILE = re.compile(r"[A-Za-z0-9_-]{1,40}\.png")
TILE_LIMIT = (40, 300 * 1024)  # pictures, bytes each


def menu_original(store: Store, serial: str) -> bytes:
    """The car's own Apps menu (SyncExtPack's SyncApps.swf), from the newest drive log."""
    report = latest_report_with(store, serial, f"{MENU_FOLDER}/SyncApps.swf")
    if report is None:
        raise ThemeError("no copy of the car's Apps menu yet: run `s2am job logger --drive` first")
    return (report / MENU_FOLDER / "SyncApps.swf").read_bytes()


def plan_menu(store: Store, serial: str, swf: Path | None, tiles: Path | None, restore: str | None,
              fetch: list[str]) -> tuple[dict, dict[str, bytes]]:
    """(job params, job folder files) for an Apps menu job: a new SyncApps.swf plus tile pictures
    in Tiles\\, or (``restore``) the car's original SyncApps.swf back. The tiles stay."""
    old = menu_original(store, serial)
    if restore:
        target = store.job(serial, restore)
        if target.get("kind") != "appmenu" or target["params"].get("restore"):
            raise ThemeError(f"{restore} is not an Apps menu job")
        if sha256(old) != target["params"]["files"]["SyncApps.swf"]["old_sha256"]:
            raise ThemeError(f"the Mac's copy of SyncApps.swf is not what {restore} replaced; not restoring it")
        return ({"restore": restore, "files": {"SyncApps.swf": len(old)},
                 "sha256": {"SyncApps.swf": sha256(old)}, "fetch": fetch_list(store, serial, fetch)},
                {"orig-SyncApps.swf": old})
    if swf is None or tiles is None:
        raise ThemeError("give --swf and --tiles (or --restore JOB)")
    new = swf.read_bytes()
    if not whole_flash(new) or new[3] < 6 or len(new) > 2 * 1024 * 1024:
        raise ThemeError(f"{swf} is not a Flash file SYNC's player can load")
    if new == old:
        raise ThemeError("the new Apps menu is the same as the car's; nothing to do")
    pictures = sorted(p for p in tiles.iterdir() if p.is_file() and not p.name.startswith("."))
    bad = [p.name for p in pictures if not TILE.fullmatch(p.name) or p.stat().st_size > TILE_LIMIT[1]
           or p.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"]
    if not pictures or bad or len(pictures) > TILE_LIMIT[0]:
        raise ThemeError(f"tiles must be up to {TILE_LIMIT[0]} PNG files named like AutoKitPlugin.png; bad: {bad}")
    params = {
        "fetch": fetch_list(store, serial, fetch),
        "files": {"SyncApps.swf": {"old": len(old), "new": len(new), "old_sha256": sha256(old),
                                   "new_sha256": sha256(new)}},
        "added": {f"Tiles\\{p.name}": {"new": p.stat().st_size, "new_sha256": sha256(p.read_bytes())}
                  for p in pictures},
    }
    extra = {"new-SyncApps.swf": new}
    extra.update({f"add-Tiles_{p.name}": p.read_bytes() for p in pictures})
    return params, extra


APPS_FOLDER = "skins/8inchSkins/Ford/Sync/Apps"


def screen_original(store: Store, serial: str, screen: str) -> bytes:
    """The car's own copy of one of Ford's screens, from the newest drive log."""
    if screen not in SCREENS + STARTUP_SCREENS:
        raise ThemeError(f"s2am does not change {screen}; it may change {', '.join(SCREENS + STARTUP_SCREENS)}")
    report = latest_report_with(store, serial, f"{APPS_FOLDER}/{screen}")
    if report is None:
        raise ThemeError("no copy of that screen yet: run `s2am job logger --drive` first")
    return (report / APPS_FOLDER / screen).read_bytes()


def replaced_screen(store: Store, serial: str, target: dict) -> bytes:
    """What a screen job really replaced: the backup its stick brought back (the car's own bytes,
    even if they were not what the Mac planned against), else a drive log's copy with the hash
    the job recorded, from any drive log, not only the newest."""
    screen = target["params"]["screen"]
    name = screen.rsplit("/", 1)[1]
    report = store.report(serial, target["id"])
    backup = report / "backup" / name if report else None
    if backup and backup.is_file() and backup.stat().st_size == target["params"]["files"][name]["old"]:
        return backup.read_bytes()
    want = target["params"]["files"][name]["old_sha256"]
    for record in reversed(store.jobs(serial)):
        copy = store.report(serial, record["id"])
        copy = copy / APPS_FOLDER / screen if copy else None
        if copy and copy.is_file() and sha256(copy.read_bytes()) == want:
            return copy.read_bytes()
    raise ThemeError(f"no copy of what {target['id']} replaced: import its stick first, or keep the drive log")


def plan_screen(store: Store, serial: str, screen: str | None, swf: Path | None, restore: str | None,
                fetch: list[str], startup: bool = False) -> tuple[dict, dict[str, bytes]]:
    """(job params, job folder files) for a screen job: one of Ford's screens replaced by a
    version built on this Mac from the car's own (sync-redesign), or (``restore``) Ford's back.
    A screen SYNC loads at start-up is changed only with ``startup``; putting one back never
    needs it."""
    if restore:
        target = store.job(serial, restore)
        if target.get("kind") != "screen" or target["params"].get("restore"):
            raise ThemeError(f"{restore} is not a screen job")
        screen = target["params"]["screen"]
        old, name = replaced_screen(store, serial, target), screen.rsplit("/", 1)[1]
        return ({"restore": restore, "screen": screen, "files": {name: len(old)}, "sha256": {name: sha256(old)},
                 "fetch": fetch_list(store, serial, fetch)},
                {f"orig-{name}": old})
    if screen is None or swf is None:
        raise ThemeError("give --screen and --swf (or --restore JOB)")
    if screen in STARTUP_SCREENS and not startup:
        raise ThemeError(f"{screen} loads when SYNC starts: a fault in it can leave the screen dark until the "
                         "undo stick runs. Build the undo stick with it, and give --startup to go ahead")
    old, new, name = screen_original(store, serial, screen), swf.read_bytes(), screen.rsplit("/", 1)[1]
    if not whole_flash(new) or new[3] != old[3] or len(new) > 2 * 1024 * 1024:
        raise ThemeError(f"{swf} is not a Flash file of the same version as Ford's {name}")
    if new == old:
        raise ThemeError("the new screen is the same as the car's; nothing to do")
    if len(new) == len(old):  # the car tells a copy that failed (a locked file) only by its size
        raise ThemeError(f"the new {name} is exactly as long as Ford's, so the car could not tell a failed "
                         "copy from a good one: rebuild it")
    params = {"screen": screen, "fetch": fetch_list(store, serial, fetch),
              "files": {name: {"old": len(old), "new": len(new), "old_sha256": sha256(old),
                               "new_sha256": sha256(new)}}}
    if screen in STARTUP_SCREENS:
        params["startup"] = True  # recorded, and checked again wherever its script is written
    return params, {f"new-{name}": new}


def verify(report: Path, params: dict, kind: str = "theme") -> str:
    """After import: did the car end up with exactly the planned files (and a whole backup)?"""
    applied = report / "applied"
    name = {"theme": "theme", "appmenu": "Apps menu"}.get(kind, "screen")
    if params.get("restore"):
        expected = params["sha256"]
        what = f"the original {name} is back"
    else:
        expected = {n: f["new_sha256"] for n, f in params["files"].items()}
        expected.update({n.replace("\\", "_"): f["new_sha256"] for n, f in (params.get("added") or {}).items()})
        what = f"the new {name} is on the car"
        backup = report / "backup"
        bad = [n for n, f in params["files"].items()
               if not (backup / n).is_file() or sha256((backup / n).read_bytes()) != f["old_sha256"]]
        if bad:
            return f"NOT verified: the backup on the stick is missing or differs: {bad}"
    wrong = [n for n, h in expected.items()
             if not (applied / n).is_file() or sha256((applied / n).read_bytes()) != h]
    if wrong:
        return f"NOT verified: these files on the car are not the planned ones: {wrong}"
    return f"verified: {what} ({len(expected)} files match byte for byte)"
