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
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import patch_waveout

REPO = Path(__file__).resolve().parents[1]
UPSTREAM = REPO.parent / "syncextpack"
IMAGE = "sync2-auto-magic-builder"
DEFAULT_APPS = ("AutoKit", "Explorer", "Reboot")

AUTOKIT_DIR = Path("FullPack/SyncExtendedPack/Apps/Media/AutoKit")
HOOK_SOURCE = Path("FullPack/SyncExtendedPack/Apps/Media/VideoPlayer_EN/WaveOutHooks.dll")
PATCH_TARGETS = ("AutoKit.exe", "libgstwaveoutsink.dll", "libgstwaveform.dll")
STAGE_IGNORE = shutil.ignore_patterns(".git", "*.rar", "SyncExtPack_*.zip", "builder.log")

# Upstream validateSerial: 8 characters, no letter O. The serial also lands in
# a shell command inside crypto_pack_docker.sh upstream, so keep it strict.
SERIAL = re.compile(r"[0-9A-NP-Z]{8}")
APP_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class BuildError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_thru(now: datetime) -> datetime:
    """Last moment the current crypto_pack key bucket (magic 0) is valid."""
    def bucket(moment: datetime) -> int:
        return int(moment.timestamp() / (60 * 60 * 24 * 30) - 0.48)

    current, step, moment = bucket(now), timedelta(hours=1), now
    while bucket(moment + step) == current:
        moment += step
    while bucket(moment + timedelta(seconds=1)) == current:
        moment += timedelta(seconds=1)
    return moment


def stage(upstream: Path, staging: Path) -> list[dict]:
    """Copy upstream into staging and apply the AutoKit audio patch."""
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(upstream, staging, symlinks=True, ignore=STAGE_IGNORE)

    autokit = staging / AUTOKIT_DIR
    hook = staging / HOOK_SOURCE
    changes = []
    for name in PATCH_TARGETS:
        module = autokit / name
        original = module.read_bytes()
        try:
            patched = patch_waveout.patch(original, hook.read_bytes())
        except patch_waveout.PatchError as error:
            raise BuildError(f"{name}: {error}") from error
        module.with_name(name + ".orig").write_bytes(original)
        module.write_bytes(patched)
        changes.append({"file": name, "original_sha256": hashlib.sha256(original).hexdigest(),
                        "patched_sha256": hashlib.sha256(patched).hexdigest()})
    shutil.copy2(hook, autokit / patch_waveout.HOOK_DLL_NAME)
    changes.append({"file": patch_waveout.HOOK_DLL_NAME, "added_from": str(HOOK_SOURCE),
                    "sha256": sha256(hook)})

    # Inside the container crypto_pack runs directly and swfmill comes from apt.
    (staging / "crypto_pack_docker.sh").unlink(missing_ok=True)
    swfmill = staging / "FlashTools" / "swfmill"
    if swfmill.is_symlink() or swfmill.exists():
        swfmill.unlink()
    swfmill.symlink_to("/usr/bin/swfmill")
    (staging / "crypto_pack").chmod(0o755)
    return changes


DOCKER_DESKTOP_BIN = Path("/Applications/Docker.app/Contents/Resources/bin")


def docker() -> list[str]:
    binary = shutil.which("docker") or str(DOCKER_DESKTOP_BIN / "docker")
    if not Path(binary).exists():
        raise BuildError("Docker CLI not found; start Docker Desktop")
    return [binary]


def docker_env() -> dict[str, str]:
    env = dict(os.environ)
    # The CLI's credential helper (docker-credential-desktop) lives here.
    if DOCKER_DESKTOP_BIN.is_dir():
        env["PATH"] = f"{DOCKER_DESKTOP_BIN}{os.pathsep}{env.get('PATH', '')}"
    socket = Path.home() / ".docker" / "run" / "docker.sock"
    if "DOCKER_HOST" not in env and socket.exists():
        env["DOCKER_HOST"] = f"unix://{socket}"
    return env


def run_upstream(staging: Path, serial: str, apps: tuple[str, ...]) -> None:
    env = docker_env()
    subprocess.run(docker() + ["build", "--platform", "linux/amd64", "-q", "-t", IMAGE,
                               str(REPO / "docker")], check=True, env=env,
                   stdout=subprocess.DEVNULL)
    steps = [
        ["python3", "build_pack.py", serial, "SyncExtPack/pack_install.bin", "0", *apps],
        ["python3", "build_pack.py", serial, "SyncExtPack/update.bin", "0", "UpdateService"],
        ["python3", "build_installer.py", serial],
    ]
    for step in steps:
        subprocess.run(docker() + ["run", "--rm", "--platform", "linux/amd64",
                                   "--network", "none", "-u", f"{os.getuid()}:{os.getgid()}",
                                   "-e", "HOME=/tmp", "-v", f"{staging}:/work", "-w", "/work",
                                   IMAGE, *step],
                       check=True, env=env)


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
        archive = write_package(collect(args.staging.resolve(), serial), args.output,
                                serial, apps, changes, expires)
    except (BuildError, subprocess.CalledProcessError, OSError) as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    print(f"package: {archive}")
    print(f"install before {expires:%Y-%m-%d %H:%M} UTC (the pack key changes every 30 days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
