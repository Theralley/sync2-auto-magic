"""Which files belong to which SYNC 2 app, and how to take an app out of the Apps menu.

The catalog is read from SyncExtPack's own unit definitions (builder/units/*.py)
with `ast`, so no upstream code runs. A menu entry is the triple the builder
writes into SyncApps.xml: name, plugin ("native") and icon. An app also owns the
files its unit installs; those are what --purge deletes.
"""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from xml.dom.minidom import parseString

from .state import Entry

UNIT_FILES = ("builder/units/app_units.py", "builder/units/service_units.py")
ICON_PREFIX = "Apps/Info/SyncApps/Icons/"
ICONS_DIR = "/8inchSkins/Ford/Sync/Apps/Info/SyncApps/Icons/"
APPS_DIR = "/SyncExtendedPack/Apps/"
# Never deleted, whatever a catalog says: the updater, the app launcher, shared folders.
PROTECTED = ("/windows/updateservice.dll", "/syncextendedpack/apps/tools/syncappsrunner")


MENU_KINDS = ("rm", "undo")  # job kinds that change SyncApps.xml


class AppError(Exception):
    pass


@dataclass
class CatalogApp:
    name: str
    plugin: str
    icon: str
    files: set[str] = field(default_factory=set)  # car paths, folders end with "/"


def catalog(upstream: Path) -> dict[str, CatalogApp]:
    """Menu name (lower case) -> the app's plugin, icon and installed files."""
    classes: dict[str, dict] = {}
    for relative in UNIT_FILES:
        tree = ast.parse((upstream / relative).read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            info = {"bases": [b.id for b in node.bases if isinstance(b, ast.Name)]}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                    target = stmt.targets[0].id
                    if target == "FILES":
                        info["files"] = ast.literal_eval(stmt.value)
                    elif target == "APP_CONFIG" and isinstance(stmt.value, ast.Call):
                        info["config"] = [ast.literal_eval(a) for a in stmt.value.args]
            classes[node.name] = info

    def inherited(name: str, key: str):
        info = classes.get(name, {})
        if key in info:
            return info[key]
        for base in info.get("bases", []):
            value = inherited(base, key)
            if value is not None:
                return value
        return None

    apps: dict[str, CatalogApp] = {}
    for name in classes:
        config = inherited(name, "config")
        if not config:
            continue
        app = apps.setdefault(config[0].lower(), CatalogApp(config[0], config[1], config[2]))
        for item in inherited(name, "files") or []:
            app.files.add(item[1] if isinstance(item, tuple) else item)
    return apps


def menu_entries(xml: bytes) -> list[tuple[str, str, str]]:
    """(name, plugin, icon path) for every slot, empty slots included."""
    root = ElementTree.fromstring(xml)
    return [(app.get("name", ""), (app.findtext("native") or "").strip(),
             (app.findtext("iconPath") or "").strip()) for app in root.iter("app")]


def render_menu(entries: list[tuple[str, str, str]]) -> bytes:
    """SyncApps.xml exactly as SyncExtPack's BaseFlashUnit writes it."""
    root = ElementTree.Element("root")
    apps = ElementTree.SubElement(root, "apps")
    for name, plugin, icon in entries:
        app = ElementTree.SubElement(apps, "app", name=name)
        ElementTree.SubElement(app, "native").text = plugin
        ElementTree.SubElement(app, "iconPath").text = icon
    return parseString(ElementTree.tostring(root)).toprettyxml().encode()


@dataclass
class Removal:
    app: str
    menu_before: bytes
    menu_after: bytes
    delete_dirs: list[str]
    delete_files: list[str]
    kept: list[str]          # owned files left alone, with the reason
    executables: list[str]   # process names that must not be running during a purge


SAFE_COMPONENT = re.compile(r"[A-Za-z0-9 _.\-]+")


def _allowed(path: str, plugin: str) -> bool:
    """May s2am delete this car path? Literal paths only: MortScript treats * and ? as masks."""
    folder = path.endswith("/")
    parts = path.strip("/").split("/")
    if not path.startswith("/") or any(not SAFE_COMPONENT.fullmatch(p) or p in (".", "..")
                                       or p.strip(". ") != p for p in parts):
        return False
    lower = "/" + "/".join(parts).lower()
    if any(lower.startswith(p) for p in PROTECTED):
        return False
    apps_parts = APPS_DIR.strip("/").lower().split("/")
    under_apps = [p.lower() for p in parts[:2]] == apps_parts
    if folder:  # an app folder: exactly /SyncExtendedPack/Apps/<Category>/<App>/
        return under_apps and len(parts) == 4
    if lower.startswith("/windows/"):
        return lower == f"/windows/{plugin.lower()}.dll"
    if lower.startswith(ICONS_DIR.lower()):
        return len(parts) == len(ICONS_DIR.strip("/").split("/")) + 1
    return under_apps and len(parts) >= 4  # a single file, e.g. Tools/explorer.exe


def plan_removal(app_name: str, menu: bytes, inventory: list[Entry],
                 apps: dict[str, CatalogApp], purge: bool) -> Removal:
    """What removing ``app_name`` changes, judged against the car's last report."""
    entries = menu_entries(menu)
    matches = [i for i, e in enumerate(entries) if e[0] and e[0].lower() == app_name.lower()]
    if len(matches) != 1:
        names = [e[0] for e in entries if e[0]]
        raise AppError(f"{app_name!r} is {'not' if not matches else 'more than once'} in the "
                       f"Apps menu; the menu has {names}")
    index = matches[0]
    name, plugin, icon = entries[index]
    after = list(entries)
    after[index] = ("", "", "")

    dirs, files, kept, exes = [], [], [], []
    if purge:
        known = apps.get(name.lower())
        if known is None:
            raise AppError(f"{name!r} is not a SyncExtPack app, so its files are unknown; "
                           "remove it from the menu without --purge")
        sharing = [e[0] or "(an unnamed slot)" for e in after if e[1] and e[1].lower() == plugin.lower()]
        if sharing:  # the other entry runs the same plugin, so it needs the same files
            raise AppError(f"{sharing} also use the plugin {plugin!r}; purging would break them. "
                           "Remove without --purge, or remove those entries first")
        icons_in_use = {e[2].lower() for e in after if e[2]}
        owners = {path.lower(): other.name for other in apps.values() if other is not known
                  for path in other.files}
        present = {e.path.replace("\\", "/").lower(): e for e in inventory}
        for path in sorted(known.files):
            reason = None
            if not _allowed(path, plugin):
                reason = "outside what s2am may delete"
            elif path.lower() in owners:
                reason = f"also installed by {owners[path.lower()]!r}"
            elif path.startswith(ICONS_DIR) and \
                    (ICON_PREFIX + path.rsplit("/", 1)[-1]).lower() in icons_in_use:
                reason = "icon still used by another menu entry"
            if reason:
                kept.append(f"{path} ({reason})")
            elif path.endswith("/"):
                dirs.append(path)
                folder = path.rstrip("/").lower()
                exes += sorted({e.path.rsplit("\\", 1)[-1] for key, e in present.items()
                                if key.startswith(folder + "/") and key.endswith(".exe")})
                # A .reg file (AutoKit's box.reg registers a USB driver) was applied to the
                # car's registry; those entries stay, pointing at files that are gone.
                kept += [f"registry entries from {e.path} (s2am does not edit the registry)"
                         for key, e in sorted(present.items())
                         if key.startswith(folder + "/") and key.endswith(".reg")]
            else:
                files.append(path)
                if path.lower().endswith(".exe"):
                    exes.append(path.rsplit("/", 1)[-1])
    return Removal(name, menu, render_menu(after), dirs, files, kept, sorted(set(exes)))
