"""The first install: put SyncExtPack's four files on a stick, then do the rename step.

SyncExtPack's own procedure (SYNCEXTPACK_INSTALLATION.md): the stick carries
SyncExtPack/{Installer.jpg, UpdateInstaller.dll, update.bin, pack_install.bin};
the wallpaper picker runs Installer.jpg, which installs UpdateService and
restarts SYNC; then pack_install.bin is renamed to install.bin and the stick
goes back in, and UpdateService installs the apps. The rename is what keeps
UpdateService from running the app pack too early, so prepare refuses any
stick that already carries an install.bin.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import window
from .container import REPO

FILES = ("Installer.jpg", "UpdateInstaller.dll", "update.bin", "pack_install.bin")
DEFAULT_APPS = ("AutoKit", "Explorer", "Reboot")
RECORD = Path("s2am") / "bootstrap.json"


class BootstrapError(Exception):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(serial: str, output: Path, apps: tuple[str, ...] = DEFAULT_APPS) -> Path:
    """Run tools/make_pack.py and return the manifest it wrote."""
    result = subprocess.run([sys.executable, str(REPO / "tools" / "make_pack.py"), serial,
                             *apps, "--output", str(output)])
    manifest = output / f"SyncExtPack_{serial}_{'_'.join(apps)}_audiofix.manifest.json"
    if result.returncode or not manifest.is_file():
        raise BootstrapError("make_pack failed; see its output above")
    return manifest


def _load(manifest: Path, serial: str, now: datetime,
          apps: tuple[str, ...] = DEFAULT_APPS) -> tuple[dict, Path]:
    data = json.loads(manifest.read_text())
    archive = manifest.with_name(manifest.name.replace(".manifest.json", ".zip"))
    if data.get("serial") != serial:
        raise BootstrapError(f"pack was built for {data.get('serial')}, not {serial}")
    if sorted(data.get("usb_files", {})) != sorted(FILES):
        raise BootstrapError(f"manifest lists {sorted(data.get('usb_files', {}))}, "
                             f"expected {sorted(FILES)}")
    if tuple(data.get("apps", ())) != apps:
        raise BootstrapError(f"pack holds apps {data.get('apps')}, expected {list(apps)}")
    if not archive.is_file() or _sha256(archive) != data.get("archive_sha256"):
        raise BootstrapError(f"{archive.name} is missing or does not match its manifest")
    expires = datetime.fromisoformat(data["install_before_utc"])
    if expires <= now:
        raise BootstrapError(f"pack expired {expires:%Y-%m-%d %H:%M} UTC; build a new one")
    return data, archive


def prepare(stick: Path, serial: str, manifest: Path, now: datetime | None = None,
            force: bool = False, apps: tuple[str, ...] = DEFAULT_APPS) -> dict:
    """Write the four stage-one files to the stick and record what was written."""
    now = now or datetime.now(timezone.utc)
    data, archive = _load(manifest, serial, now, apps)
    if datetime.fromisoformat(data["install_before_utc"]) - now < window.DEFAULT_MARGIN \
            and not force:
        raise BootstrapError("pack expires within two days; build in the next window, or force")

    target = stick / "SyncExtPack"
    existing = sorted(p.name for p in target.iterdir()) if target.is_dir() else []
    if existing and not force:
        raise BootstrapError(f"stick already has SyncExtPack/{existing}; use a clean stick "
                             "or force to move them aside")
    if existing:
        aside = stick / "s2am" / "history" / now.strftime("%Y%m%d-%H%M%S")
        aside.mkdir(parents=True)
        for name in existing:
            shutil.move(str(target / name), str(aside / name))
    target.mkdir(exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
        if names != sorted(f"SyncExtPack/{n}" for n in FILES):
            raise BootstrapError(f"unexpected archive contents {names}")
        for name in FILES:
            content = zf.read(f"SyncExtPack/{name}")
            if not content:
                raise BootstrapError(f"{name} in the archive is empty")
            (target / name).write_bytes(content)
    for name in FILES:  # read back what is on the stick, not what we meant to write
        if _sha256(target / name) != data["usb_files"][name]:
            raise BootstrapError(f"{name} on the stick does not match the build")
    if (target / "install.bin").exists():  # would let UpdateService run the apps too early
        raise BootstrapError("SyncExtPack/install.bin must not exist before stage one")

    record = {"serial": serial, "prepared_utc": now.isoformat(timespec="seconds"),
              "install_before_utc": data["install_before_utc"],
              "pack_install_sha256": data["usb_files"]["pack_install.bin"],
              "archive": archive.name}
    (stick / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (stick / RECORD).write_text(json.dumps(record, indent=2) + "\n")
    return record


def prepare_apps_only(stick: Path, serial: str, manifest: Path, now: datetime | None = None,
                      force: bool = False, apps: tuple[str, ...] = DEFAULT_APPS) -> dict:
    """For a car whose UpdateService already runs job sticks: only the app pack, as install.bin.

    That is stage two without stage one; Installer.jpg and the UpdateService files stay off
    the stick.
    """
    now = now or datetime.now(timezone.utc)
    data, archive = _load(manifest, serial, now, apps)
    if datetime.fromisoformat(data["install_before_utc"]) - now < window.DEFAULT_MARGIN \
            and not force:
        raise BootstrapError("pack expires within two days; build in the next window, or force")
    pending = sorted((stick / "s2am" / "pending").glob("*.json"))
    if pending and not force:
        raise BootstrapError(f"the stick still has a job waiting ({pending[0].stem}); "
                             "import it first, or force")

    target = stick / "SyncExtPack"
    existing = sorted(p.name for p in target.iterdir()) if target.is_dir() else []
    if existing:  # earlier job runs: installed.bin would stop UpdateService's rename
        aside = stick / "s2am" / "history" / now.strftime("%Y%m%d-%H%M%S")
        aside.mkdir(parents=True, exist_ok=True)
        for name in existing:
            shutil.move(str(target / name), str(aside / name))
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        content = zf.read("SyncExtPack/pack_install.bin")
    # Written under a name UpdateService ignores, checked, and only then given the live name.
    staged = target / "pack_install.bin"
    staged.write_bytes(content)
    if _sha256(staged) != data["usb_files"]["pack_install.bin"]:
        staged.unlink()
        raise BootstrapError("the app pack on the stick does not match the build")
    staged.rename(target / "install.bin")

    record = {"serial": serial, "mode": "apps-only",
              "prepared_utc": now.isoformat(timespec="seconds"),
              "finished_utc": now.isoformat(timespec="seconds"),
              "install_before_utc": data["install_before_utc"],
              "pack_install_sha256": data["usb_files"]["pack_install.bin"],
              "archive": archive.name}
    (stick / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (stick / RECORD).write_text(json.dumps(record, indent=2) + "\n")
    return record


def finish(stick: Path, now: datetime | None = None) -> dict:
    """The rename step: pack_install.bin becomes install.bin, after checks."""
    now = now or datetime.now(timezone.utc)
    target = stick / "SyncExtPack"
    try:
        record = json.loads((stick / RECORD).read_text())
    except (OSError, ValueError) as error:
        raise BootstrapError(f"no readable {RECORD} on the stick; run bootstrap prepare") from error
    source, install = target / "pack_install.bin", target / "install.bin"
    if install.exists():
        raise BootstrapError("SyncExtPack/install.bin already exists; nothing to rename")
    if not source.is_file() or source.is_symlink():
        raise BootstrapError("SyncExtPack/pack_install.bin is missing")
    if _sha256(source) != record.get("pack_install_sha256"):
        raise BootstrapError("pack_install.bin does not match the prepared build")
    if datetime.fromisoformat(record["install_before_utc"]) <= now:
        raise BootstrapError("pack has expired; build and prepare a new one")
    # Anything UpdateService left behind (installed.bin, a log) would confuse the next run.
    for name in ("installed.bin", "install_log.txt"):
        if (target / name).exists():
            aside = stick / "s2am" / "history" / now.strftime("%Y%m%d-%H%M%S")
            aside.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target / name), str(aside / name))
    source.rename(install)
    if _sha256(install) != record["pack_install_sha256"]:
        raise BootstrapError("install.bin does not match after the rename; re-run prepare")
    record["finished_utc"] = now.isoformat(timespec="seconds")
    (stick / RECORD).write_text(json.dumps(record, indent=2) + "\n")
    return record
