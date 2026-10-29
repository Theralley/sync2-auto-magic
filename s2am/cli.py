"""s2am command line.

    s2am window                                  key window and whether it is safe to build
    s2am stick check /Volumes/STICK              FAT32, MBR, size, nothing left to run
    s2am bootstrap prepare --serial S --stick /Volumes/STICK   first install, stage one
    s2am bootstrap finish /Volumes/STICK         first install, the rename step
    s2am job inventory --serial XXXXXXXX         build an inventory job (install.bin)
    s2am job autokit-stock|autokit-patched ...   swap AutoKit's audio modules, then inventory
    s2am stick prepare /Volumes/STICK --job DIR  put that job on a stick
    s2am stick import /Volumes/STICK             read back what the car wrote
    s2am status --serial XXXXXXXX                apps, plugins and menu from the last report
    s2am diff --serial XXXXXXXX [OLD NEW]        what changed between two reports
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from . import bootstrap, diskcheck, pack, stick, window
from .container import REPO, ContainerError
from .job import AUTOKIT_CE, AUTOKIT_MODULES, SERIAL, Job, stage
from .state import Store, diff, parse_inventory

UPSTREAM = REPO.parent / "syncextpack"


def _serial(value: str) -> str:
    value = value.upper()
    if not SERIAL.fullmatch(value):
        raise argparse.ArgumentTypeError("serial must be 8 characters, A-Z/0-9, without O")
    return value


def _record(job: Job, status: str, **extra) -> dict:
    return {**json.loads(job.to_json()), "status": status, **extra}


def cmd_window(args) -> int:
    safe, end = window.check(datetime.now(timezone.utc))
    print(f"current key window ends {end:%Y-%m-%d %H:%M} UTC")
    print("safe to build and install" if safe else
          "too close to a window boundary: wait, or use --force")
    return 0 if safe else 1


JOB_KINDS = {"inventory": "inv", "autokit-stock": "akstock", "autokit-patched": "akpatch"}
MARK = {"ok": "✓", "warn": "!", "fail": "✗"}


def _eject(stick_path: Path, args) -> None:
    if args.no_eject or args.any_path:
        return
    result = subprocess.run(["diskutil", "eject", str(stick_path)], capture_output=True, text=True)
    print("stick ejected" if result.returncode == 0 else
          f"eject failed, eject it in Finder before pulling it: {result.stderr.strip()}")


def _stick_findings(stick_path: Path, args) -> bool:
    """Print the stick check; True when the stick passes."""
    findings = diskcheck.check(stick_path, info=None if args.any_path else diskcheck.diskutil_info)
    for finding in findings:
        print(f"  {MARK[finding.level]} {finding.message}")
    return not diskcheck.failed(findings)


def cmd_stick_check(args) -> int:
    print(f"checking {args.stick}")
    return 0 if _stick_findings(Path(args.stick), args) else 1


def cmd_bootstrap_prepare(args) -> int:
    stick_path = Path(args.stick)
    if not _stick_findings(stick_path, args) and not args.force:
        raise bootstrap.BootstrapError("stick check failed; fix the stick or use --force")
    safe, end = window.check(datetime.now(timezone.utc))
    if not safe and not args.force:
        raise bootstrap.BootstrapError(f"too close to a key window boundary (ends {end:%Y-%m-%d %H:%M} "
                                       "UTC); wait, or use --force")
    manifest = Path(args.manifest) if args.manifest else bootstrap.build(
        args.serial, REPO / "build" / "out")
    record = bootstrap.prepare(stick_path, args.serial, manifest, force=args.force)
    print(f"stage one is on {stick_path}; install before {record['install_before_utc']} UTC")
    print("in the car: Settings > Display > Wallpaper > Add > USB > Installer.jpg, wait for "
          "the restart, then pull the stick and run: s2am bootstrap finish " + str(stick_path))
    _eject(stick_path, args)
    return 0


def cmd_bootstrap_finish(args) -> int:
    stick_path = Path(args.stick)
    bootstrap.finish(stick_path)
    print("ready: SyncExtPack/install.bin is in place. Insert the stick and wait for "
          "'Install successfully completed!'")
    _eject(stick_path, args)
    return 0


def cmd_job(args) -> int:
    job = Job(serial=args.serial, kind=JOB_KINDS[args.kind])
    workdir = Path(args.work or REPO / "build" / "jobs" / job.id).resolve()
    stage(job, args.upstream, workdir)
    if args.no_pack:
        print(f"staged {job.id} at {workdir} (not packed)")
        return 0
    install = pack.build(job, workdir, args.upstream, force=args.force)
    Store().save_job(job.serial, job.id,
                     _record(job, "built", install_sha256=pack.sha256(install)))
    print(f"job {job.id}: {install}")
    print(f"next: s2am stick prepare /Volumes/<STICK> --job {workdir}")
    return 0


def cmd_stick_prepare(args) -> int:
    workdir = Path(args.job)
    job = Job.from_json((workdir / "job.json").read_text())
    install = workdir / "install.bin"
    if not install.is_file():
        raise stick.StickError(f"{install} is missing; build the job first")
    archive = stick.prepare(Path(args.stick), install, job, require_volume=not args.any_path)
    Store().save_job(job.serial, job.id, _record(job, "on-stick"))
    print(f"job {job.id} is on {args.stick}")
    if archive.exists():
        print(f"earlier UpdateService files moved to {archive}")
    print("in the car: insert the stick, wait for 'Install successfully completed', pull it")
    return 0


def cmd_stick_import(args) -> int:
    results = stick.import_reports(Path(args.stick), Store(), require_volume=not args.any_path)
    if not results:
        print("no s2am jobs on this stick")
    for record in results:
        note = " (stick was inserted again; nothing ran twice)" if record.get("replayed") else ""
        reason = f" ({record['reason']})" if record.get("reason") else ""
        print(f"{record['id']}: {record['status']}{note}{reason}")
    return 0 if all(r["status"] in ("applied", "already-applied", "pending") for r in results) else 1


def _menu(report: Path) -> list[str]:
    xml = report / "SyncApps.xml"
    if not xml.exists():
        return []
    try:
        root = ElementTree.fromstring(xml.read_bytes())
    except ElementTree.ParseError:
        return ["(SyncApps.xml did not parse)"]
    return [app.get("name") for app in root.iter("app") if app.get("name")]


def cmd_status(args) -> int:
    store = Store()
    latest = store.latest_inventory(args.serial)
    if latest is None:
        print(f"no inventory for {args.serial} yet: run 's2am job inventory --serial {args.serial}'")
        return 1
    job_id, entries, info = latest
    apps = sorted({"\\".join(e.path.split("\\")[:5]) for e in entries
                   if e.kind == "D" and e.path.lower().count("\\") >= 4})
    plugins = sorted(e.path.rsplit("\\", 1)[-1] for e in entries
                     if e.kind == "F" and e.path.lower().startswith("\\windows\\"))
    print(f"car {args.serial}, report {job_id}")
    for key in ("time", "mortscript", "free"):
        if key in info:
            print(f"  {key}: {info[key]}")
    print(f"  apps ({len(apps)}):")
    for app in apps:
        files = [e for e in entries if e.kind == "F" and e.path.lower().startswith(app.lower() + "\\")]
        print(f"    {app}  {len(files)} files, {sum(e.size or 0 for e in files)} B")
    print(f"  plugins: {', '.join(plugins) or '-'}")
    menu = _menu(store.report(args.serial, job_id))
    print(f"  menu: {', '.join(menu) or 'missing from the report (SyncApps.xml not copied)'}")
    print(f"  AutoKit audio modules: {autokit_variant(entries)}")
    return 0


def autokit_variant(entries) -> str:
    """Which copy each patched module matches, judged by file size from the inventory."""
    sizes = {e.path.lower(): e.size for e in entries if e.kind == "F"}
    base = AUTOKIT_CE.lower()
    states = []
    for module in AUTOKIT_MODULES:
        live = sizes.get(f"{base}\\{module}".lower())
        stock = sizes.get(f"{base}\\{module}.orig".lower())
        patched = sizes.get(f"{base}\\{module}.patched".lower())
        if live is None:
            states.append("missing")
        elif patched is not None and live == patched and live != stock:
            states.append("patched")
        elif stock is not None and live == stock and live != patched:
            states.append("stock")
        else:
            states.append("unknown")
    if len(set(states)) == 1:
        return f"{states[0]} (all {len(states)})"
    return "mixed: " + ", ".join(f"{m}={s}" for m, s in zip(AUTOKIT_MODULES, states))


def cmd_diff(args) -> int:
    store = Store()
    if bool(args.old) != bool(args.new):
        print("give both OLD and NEW report ids, or neither", file=sys.stderr)
        return 1
    imported = [r["id"] for r in store.successful(args.serial)]
    old_id, new_id = (args.old, args.new) if args.old else (imported[-2:] + [None, None])[:2]
    if not old_id or not new_id:
        print("need two imported reports to compare", file=sys.stderr)
        return 1

    def load(job_id: str):
        report = store.report(args.serial, job_id)
        if report is None or not (report / "inventory.txt").is_file():
            raise ValueError(f"no inventory for report {job_id}")
        return parse_inventory((report / "inventory.txt").read_text(errors="replace"))

    changes = diff(load(old_id), load(new_id))
    print(f"{old_id} -> {new_id}: {len(changes)} change(s)")
    for line in changes:
        print(f"  {line}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="s2am", description=__doc__.splitlines()[0])
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("window", help="key window status").set_defaults(func=cmd_window)

    boot = sub.add_parser("bootstrap", help="first SyncExtPack install")
    boot_sub = boot.add_subparsers(dest="action", required=True)
    boot_prepare = boot_sub.add_parser("prepare")
    boot_prepare.add_argument("--serial", type=_serial, required=True)
    boot_prepare.add_argument("--stick", required=True)
    boot_prepare.add_argument("--manifest", help="use an existing make_pack manifest instead of building")
    boot_finish = boot_sub.add_parser("finish")
    boot_finish.add_argument("stick")
    for command, func in ((boot_prepare, cmd_bootstrap_prepare), (boot_finish, cmd_bootstrap_finish)):
        command.add_argument("--any-path", action="store_true",
                             help="allow a folder outside /Volumes; skips disk checks and eject")
        command.add_argument("--no-eject", action="store_true")
        command.set_defaults(func=func, force=False)
    boot_prepare.add_argument("--force", action="store_true",
                              help="accept a failed stick check, a near window boundary, or old files")

    job = sub.add_parser("job", help="build a job")
    job.add_argument("kind", choices=list(JOB_KINDS))
    job.add_argument("--serial", type=_serial, required=True)
    job.add_argument("--upstream", type=Path, default=UPSTREAM)
    job.add_argument("--work", help="staging folder (default build/jobs/<id>)")
    job.add_argument("--no-pack", action="store_true", help="stage only, skip crypto_pack")
    job.add_argument("--force", action="store_true", help="build even near a window boundary")
    job.set_defaults(func=cmd_job)

    stick_cmd = sub.add_parser("stick", help="prepare or import a USB stick")
    stick_sub = stick_cmd.add_subparsers(dest="action", required=True)
    check = stick_sub.add_parser("check")
    check.add_argument("stick")
    check.add_argument("--any-path", action="store_true", help="skip the disk-level checks")
    check.set_defaults(func=cmd_stick_check)
    prepare = stick_sub.add_parser("prepare")
    prepare.add_argument("stick")
    prepare.add_argument("--job", required=True, help="the job's staging folder")
    prepare.add_argument("--any-path", action="store_true", help="allow a folder outside /Volumes")
    prepare.set_defaults(func=cmd_stick_prepare)
    imp = stick_sub.add_parser("import")
    imp.add_argument("stick")
    imp.add_argument("--any-path", action="store_true", help="allow a folder outside /Volumes")
    imp.set_defaults(func=cmd_stick_import)

    status = sub.add_parser("status", help="state from the last report")
    status.add_argument("--serial", type=_serial, required=True)
    status.set_defaults(func=cmd_status)

    difference = sub.add_parser("diff", help="compare two reports")
    difference.add_argument("--serial", type=_serial, required=True)
    difference.add_argument("old", nargs="?")
    difference.add_argument("new", nargs="?")
    difference.set_defaults(func=cmd_diff)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (pack.PackError, stick.StickError, bootstrap.BootstrapError, ContainerError,
            ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"s2am: {error}", file=sys.stderr)
        return 1
