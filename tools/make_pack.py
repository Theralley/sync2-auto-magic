#!/usr/bin/env python3
"""Build a SyncExtPack USB package with AutoKit's audio routed through SYNC 2.

The upstream syncextpack clone is never modified. Each run copies it to a
staging folder, swaps in AutoKit modules patched by patch_waveout.py (keeping
the originals next to them as *.orig for rollback from Total Commander), adds
WaveOutHooks.dll, and runs the upstream build inside a Linux container. Unlike
the upstream scripts, every step must produce its output or the build fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from s2am import apps as apps_menu, autokit, container  # noqa: E402
from s2am.job import AUTOKIT_MODULES, LOCAL_JUNK  # noqa: E402
from s2am.window import valid_thru  # noqa: E402

UPSTREAM = REPO.parent / "syncextpack"
DEFAULT_APPS = ("AutoKit", "Explorer", "Reboot")

AUTOKIT_DIR = Path("FullPack/SyncExtendedPack/Apps/Media/AutoKit")
HOOK_SOURCE = autokit.HOOK_SOURCE
PATCH_TARGETS = AUTOKIT_MODULES
STAGE_IGNORE = shutil.ignore_patterns(".git", "*.rar", "SyncExtPack_*.zip", "builder.log", *LOCAL_JUNK)

# Upstream validateSerial: 8 characters, no letter O. The serial also lands in
# a shell command inside crypto_pack_docker.sh upstream, so keep it strict.
SERIAL = re.compile(r"[0-9A-NP-Z]{8}")
APP_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class BuildError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(upstream: Path, staging: Path) -> list[dict]:
    """Copy upstream into staging and apply the AutoKit audio patch."""
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(upstream, staging, symlinks=True, ignore=STAGE_IGNORE)

    try:
        changes = autokit.patch_folder(staging / AUTOKIT_DIR, staging / HOOK_SOURCE)
    except autokit.PatchFailed as error:
        raise BuildError(str(error)) from error

    # Inside the container crypto_pack runs directly and swfmill comes from apt.
    (staging / "crypto_pack_docker.sh").unlink(missing_ok=True)
    swfmill = staging / "FlashTools" / "swfmill"
    if swfmill.is_symlink() or swfmill.exists():
        swfmill.unlink()
    swfmill.symlink_to("/usr/bin/swfmill")
    (staging / "crypto_pack").chmod(0o755)
    return changes


def run_upstream(staging: Path, serial: str, apps: tuple[str, ...]) -> None:
    container.ensure_image()
    container.run(staging, "python3", "build_pack.py", serial,
                  "SyncExtPack/pack_install.bin", "0", *apps)
    container.run(staging, "python3", "build_pack.py", serial,
                  "SyncExtPack/update.bin", "0", "UpdateService")
    container.run(staging, "python3", "build_installer.py", serial)


def collect(staging: Path, serial: str) -> Path:
    result = staging / "SyncExtPack" / serial / "SyncExtPack"
    expected = ("pack_install.bin", "update.bin", "Installer.jpg", "UpdateInstaller.dll")
    missing = [n for n in expected if not (result / n).is_file() or not (result / n).stat().st_size]
    log = staging / "builder.log"
    errors = [line for line in log.read_text(errors="replace").splitlines()
              if "ERROR" in line] if log.exists() else []
    if missing or errors:
        raise BuildError(f"upstream build failed; missing {missing}; log errors {errors}")
    return result


# What a bootstrap pack must contain once unpacked, per default app (car paths).
APP_FILES = {
    # AutoKitPlugin starts AutoKit through SyncAppsRunner; without it the menu entry does nothing.
    "AutoKit": ("windows/AutoKitPlugin.dll", "SyncExtendedPack/Apps/Media/AutoKit/AutoKit.exe",
                "SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe"),
    "Explorer": ("windows/ExplorerPlugin.dll", "SyncExtendedPack/Apps/Tools/explorer.exe"),
    "Reboot": ("windows/RebootPlugin.dll",),
}
MENU_NAMES = {"AutoKit": "AutoKit", "Explorer": "Total Commander", "Reboot": "Reboot"}
MENU_PATH = "8inchSkins/Ford/Sync/Apps/Info/SyncApps/SyncApps.xml"


def verify_packs(staging: Path, result: Path, serial: str, apps: tuple[str, ...],
                 changes: list[dict]) -> None:
    """Unpack both packs with crypto_pack itself and check what the car would receive."""
    for pack_name, folder in (("pack_install.bin", "verify_apps"), ("update.bin", "verify_update")):
        target = staging / folder
        if target.exists():
            shutil.rmtree(target)
        container.run(staging, "./crypto_pack", "-u", str((result / pack_name).relative_to(staging)),
                      folder, serial, "0", quiet=True)
    unpacked, update = staging / "verify_apps", staging / "verify_update"
    problems = []
    if not (update / "windows" / "UpdateService.dll").is_file():
        problems.append("update.bin has no windows/UpdateService.dll")
    for app in apps:
        for path in APP_FILES.get(app, ()):
            if not (unpacked / path).is_file():
                problems.append(f"pack_install.bin has no {path}")
    autokit = unpacked / AUTOKIT_DIR.relative_to("FullPack")
    for change in changes:
        if "patched_sha256" in change:
            for name, key in ((change["file"], "patched_sha256"),
                              (change["file"] + ".patched", "patched_sha256"),
                              (change["file"] + ".orig", "original_sha256")):
                if not (autokit / name).is_file() or sha256(autokit / name) != change[key]:
                    problems.append(f"AutoKit/{name} is missing or not the expected build")
        elif not (autokit / change["file"]).is_file() or \
                ("sha256" in change and sha256(autokit / change["file"]) != change["sha256"]):
            problems.append(f"AutoKit/{change['file']} is missing or not the expected build")
    menu = unpacked / MENU_PATH
    if menu.is_file():
        names = {n for n, _, _ in apps_menu.menu_entries(menu.read_bytes()) if n}
        problems += [f"menu lacks {MENU_NAMES[a]}" for a in apps if MENU_NAMES.get(a) not in names]
    else:
        problems.append("pack_install.bin has no SyncApps.xml")
    for folder in (unpacked, update):
        shutil.rmtree(folder, ignore_errors=True)
    if problems:
        raise BuildError("the built packs do not unpack as expected: " + "; ".join(problems[:6]))


def write_package(result: Path, output: Path, serial: str, apps: tuple[str, ...],
                  changes: list[dict], expires: datetime) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    name = f"SyncExtPack_{serial}_{'_'.join(apps)}_audiofix"
    archive = output / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(result.iterdir()):
            zf.write(path, f"SyncExtPack/{path.name}")
    manifest = {
        "serial": serial,
        "apps": list(apps),
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "install_before_utc": expires.isoformat(timespec="seconds"),
        "usb_files": {p.name: sha256(p) for p in sorted(result.iterdir())},
        "autokit_changes": changes,
        "archive_sha256": sha256(archive),
    }
    (output / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("serial", help="APIM serial from Settings > General > About SYNC")
    parser.add_argument("apps", nargs="*", default=list(DEFAULT_APPS),
                        help=f"upstream app units (default: {' '.join(DEFAULT_APPS)})")
    parser.add_argument("--upstream", type=Path, default=UPSTREAM)
    parser.add_argument("--staging", type=Path, default=REPO / "build" / "stage")
    parser.add_argument("--output", type=Path, default=REPO / "build" / "out")
    parser.add_argument("--dry-run", action="store_true",
                        help="stage and patch only; do not run the upstream build")
    args = parser.parse_args(argv)

    serial = args.serial.upper()
    if not SERIAL.fullmatch(serial):
        parser.error("serial must be 8 characters, A-Z/0-9, without the letter O")
    apps = tuple(args.apps)
    if "AutoKit" not in apps or not all(APP_NAME.fullmatch(a) for a in apps):
        parser.error("apps must be plain unit names and include AutoKit")

    expires = valid_thru(datetime.now(timezone.utc))
    try:
        changes = stage(args.upstream.resolve(), args.staging.resolve())
        for change in changes:
            print(json.dumps(change))
        if args.dry_run:
            print(f"staged at {args.staging}; dry run, nothing built")
            return 0
        run_upstream(args.staging.resolve(), serial, apps)
        result = collect(args.staging.resolve(), serial)
        if "AutoKit" in apps:
            verify_packs(args.staging.resolve(), result, serial, apps, changes)
        archive = write_package(result, args.output, serial, apps, changes, expires)
    except (BuildError, container.ContainerError, subprocess.CalledProcessError, OSError) as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    print(f"package: {archive}")
    print(f"install before {expires:%Y-%m-%d %H:%M} UTC (the pack key changes every 30 days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
