"""s2am command line.

    s2am window                                  key window and whether it is safe to build
    s2am job inventory --serial XXXXXXXX         build an inventory job (install.bin)
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

from . import pack, stick, window
from .container import REPO, ContainerError
from .job import SERIAL, Job, stage
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
    return 0


def cmd_job(args) -> int:
    job = Job(serial=args.serial, kind="inv")
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
    print(f"  menu: {', '.join(_menu(store.report(args.serial, job_id))) or '-'}")
    return 0


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

    job = sub.add_parser("job", help="build a job")
    job.add_argument("kind", choices=["inventory"])
    job.add_argument("--serial", type=_serial, required=True)
    job.add_argument("--upstream", type=Path, default=UPSTREAM)
    job.add_argument("--work", help="staging folder (default build/jobs/<id>)")
    job.add_argument("--no-pack", action="store_true", help="stage only, skip crypto_pack")
    job.add_argument("--force", action="store_true", help="build even near a window boundary")
    job.set_defaults(func=cmd_job)

    stick_cmd = sub.add_parser("stick", help="prepare or import a USB stick")
    stick_sub = stick_cmd.add_subparsers(dest="action", required=True)
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
    except (pack.PackError, stick.StickError, ContainerError, ValueError, OSError,
            subprocess.CalledProcessError) as error:
        print(f"s2am: {error}", file=sys.stderr)
        return 1
