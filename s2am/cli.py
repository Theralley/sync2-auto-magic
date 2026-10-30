"""s2am command line.

    s2am wizard                                  guided install: plain questions, one car trip at a time
    s2am window                                  key window and whether it is safe to build
    s2am stick check /Volumes/STICK              FAT32, MBR, size, nothing left to run
    s2am bootstrap prepare --serial S --stick /Volumes/STICK   first install, stage one
    s2am bootstrap finish /Volumes/STICK         first install, the rename step
    s2am job inventory --serial XXXXXXXX         build an inventory job (install.bin)
    s2am job autokit-stock|autokit-patched ...   swap AutoKit's audio modules, then inventory
    s2am job remove "APP" --serial S [--purge]   take an app out of the menu (--purge: delete it)
    s2am job undo JOB_ID --serial S              put a removed app back in the menu
    s2am job install "APP" --serial S            copy an app to the car and add it to the menu
    s2am apps --serial S                         installable apps and what is on the car
    s2am job autokit-config --serial S           AutoKit video: 800,480,15, software decoding
    s2am job snapshot|logger --serial S          read-only registry snapshot / 3-minute logger
    s2am report --serial S [JOB_ID]              print a report (snapshot, logger timeline)
    s2am native build                            build the WinCE helpers (CeGCC in Docker)
    s2am job native-hello --serial S             prove compiled code runs on this SYNC 2
    s2am job runner-guard --serial S [--off]     fix the frozen screen after leaving an app
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

from . import apps, autokit, bootstrap, diskcheck, native, pack, stick, window
from .container import REPO, ContainerError
from .job import AUTOKIT_CE, AUTOKIT_LANGS, AUTOKIT_MODULES, SERIAL, Job, autokit_lang_file, stage
from .state import Store, diff, parse_inventory

UPSTREAM = REPO.parent / "syncextpack"


def _serial(value: str) -> str:
    value = value.upper()
    if not SERIAL.fullmatch(value):
        raise argparse.ArgumentTypeError("serial must be 8 characters, A-Z/0-9, without O")
    return value


def _record(job: Job, status: str, **extra) -> dict:
    return {**json.loads(job.to_json()), "status": status, **extra}


def cmd_wizard(args) -> int:
    from . import wizard  # the wizard drives this module, so import it late
    return wizard.main()


def cmd_window(args) -> int:
    safe, end = window.check(datetime.now(timezone.utc))
    print(f"current key window ends {end:%Y-%m-%d %H:%M} UTC")
    print("safe to build and install" if safe else
          "too close to a window boundary: wait, or use --force")
    return 0 if safe else 1


JOB_KINDS = {"inventory": "inv", "autokit-stock": "akstock", "autokit-patched": "akpatch",
             "remove": "rm", "install": "inst", "undo": "undo", "autokit-config": "akcfg",
             "snapshot": "snap", "logger": "log", "native-hello": "hello", "runner-guard": "guard"}
MARK = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}


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
    if args.apps_only:
        record = bootstrap.prepare_apps_only(stick_path, args.serial, manifest, force=args.force)
        print(f"the app pack is on {stick_path} as install.bin; install before "
              f"{record['install_before_utc']} UTC")
        print("in the car: insert the stick, wait for 'Install successfully completed' and the "
              "restart, then pull it. Check with an inventory job.")
        _eject(stick_path, args)
        return 0
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


def _plan_remove(args) -> tuple[dict, dict]:
    """Plan a removal from the last report; prints exactly what will change."""
    report_id, entries, _, menu = _latest_menu(Store(), args.serial)
    catalog = apps.catalog(args.upstream)
    # Several apps go in one job: each is planned against the menu the previous one leaves.
    names, dirs, files, kept, exes, after = [], [], [], [], [], menu
    for name in args.app:
        plan = apps.plan_removal(name, after, entries, catalog, args.purge)
        names.append(plan.app)
        dirs += [d for d in plan.delete_dirs if d not in dirs]
        files += [f for f in plan.delete_files if f not in files]
        kept += [k for k in plan.kept if k not in kept]
        exes += [e for e in plan.executables if e not in exes]
        after = plan.menu_after
    label = ", ".join(names)
    print(f"remove {label} (planned from report {report_id}):")
    print(f"  menu: {label} {'is' if len(names) == 1 else 'are'} taken out of the Apps menu "
          "(old menu backed up on the car)")
    for path in dirs:
        print(f"  delete folder {path}")
    for path in files:
        print(f"  delete file   {path}")
    for line in kept:
        print(f"  keep          {line}")
    if not args.purge:
        print("  files stay on the car (add --purge to delete them); undo restores the menu")
    else:
        print("  undo restores the menu only; deleted files come back by reinstalling the app")
    print("  SYNC restarts after the job")
    params = {"app": label, "apps": names, "purge": args.purge, "based_on": report_id,
              "expected_len": len(menu), "new_len": len(after),
              "delete_dirs": dirs, "delete_files": files, "executables": sorted(exes)}
    return params, {"SyncApps.xml.expected": menu, "SyncApps.xml.new": after}


def _latest_menu(store: Store, serial: str) -> tuple[str, list, dict, bytes]:
    latest = store.latest_inventory(serial)
    if latest is None:
        raise apps.AppError("no report for this car yet: run an inventory job first")
    report_id, entries, info = latest
    menu_file = store.report(serial, report_id) / "SyncApps.xml"
    if not menu_file.is_file():
        raise apps.AppError(f"report {report_id} has no SyncApps.xml: run a new inventory job")
    return report_id, entries, info, menu_file.read_bytes()


def _plan_install(args) -> tuple[dict, dict, list]:
    """Plan an install from the last report; prints exactly what will be copied."""
    report_id, _, info, menu = _latest_menu(Store(), args.serial)
    plan = apps.plan_install(args.app, menu, apps.catalog(args.upstream), args.upstream,
                             args.variant, args.reinstall)
    print(f"install {plan.app!r} ({plan.variant}, planned from report {report_id}):")
    for source, car_path in plan.sources:
        print(f"  copy {car_path}" + ("  (whole folder)" if source.is_dir() else ""))
    if plan.app.lower() == "autokit":
        print("  AutoKit gets the SYNC 2 sound patch and starts in English (stock copies kept as *.orig)")
    print(f"  menu: {'add ' + plan.app + ' to the first free slot' if plan.adds_to_menu else 'unchanged (reinstall)'}")
    print(f"  size: {plan.size / 1e6:.1f} MB; close the app first (restart SYNC) if it is running")
    free = info.get("free", "")
    if free.isdigit() and plan.size > int(free) * 0.9:
        print(f"  warning: the last report showed only {int(free) / 1e6:.1f} MB free")
    print("  SYNC restarts after the job")
    params = {"app": plan.app, "variant": plan.variant, "reinstall": args.reinstall,
              "based_on": report_id, "expected_len": len(menu), "new_len": len(plan.menu_after),
              "files": [car_path for _, car_path in plan.sources],
              "delete_dirs": [], "delete_files": [], "executables": []}
    return params, {"SyncApps.xml.expected": menu, "SyncApps.xml.new": plan.menu_after}, plan.sources


def cmd_apps(args) -> int:
    """SyncExtPack apps that s2am can install, and what the last report shows on the car."""
    catalog = apps.catalog(args.upstream)
    latest = Store().latest_inventory(args.serial)
    menu, folders = set(), set()
    if latest:
        report = Store().report(args.serial, latest[0])
        xml = report / "SyncApps.xml"
        if xml.is_file():
            menu = {name.lower() for name, _, _ in apps.menu_entries(xml.read_bytes()) if name}
        folders = {e.path.replace("\\", "/").lower() + "/" for e in latest[1] if e.kind == "D"}
    print(f"apps for {args.serial}" + (f" (report {latest[0]})" if latest else " (no report yet)"))
    for app in sorted(catalog.values(), key=lambda a: a.name.lower()):
        if not app.variants:
            continue
        on_car = any(d.lower() in folders for d in app.files if d.endswith("/"))
        state = "in menu" if app.name.lower() in menu else ("files on car" if on_car else "-")
        print(f"  {app.name:18} {state:14} variants: {', '.join(sorted(app.variants))}"
              f" (default {apps.default_variant(app)})")
    return 0


def _plan_undo(args) -> tuple[dict, dict]:
    """Undo a removal, expecting the menu exactly as that removal's own report showed it."""
    store = Store()
    target = store.job(args.serial, args.job_id)
    if target.get("kind") != "rm" or target.get("status") not in ("applied", "already-applied"):
        raise apps.AppError(f"{args.job_id} is not an applied remove job")
    if target.get("undone_by"):
        raise apps.AppError(f"{args.job_id} was already undone by {target['undone_by']}")
    later = [r["id"] for r in store.successful(args.serial)
             if r.get("kind") in apps.MENU_KINDS and r["id"] != args.job_id
             and r.get("imported_utc", "") > target.get("imported_utc", "")]
    if later:
        raise apps.AppError(f"the menu was changed again later by {later}; undo those first")
    report = store.report(args.serial, args.job_id)
    menu = report / "SyncApps.xml" if report else None
    if not menu or not menu.is_file():
        raise apps.AppError(f"the report of {args.job_id} has no SyncApps.xml to check against")
    params = target.get("params", {})
    print(f"undo {args.job_id}: put {params.get('app')!r} back in the Apps menu"
          + (" (its deleted files are not restored)" if params.get("purge") else ""))
    expected = menu.read_bytes()
    return ({"target": args.job_id, "app": params.get("app"), "apps": params.get("apps"),
             "expected_len": len(expected)},
            {"SyncApps.xml.expected": expected})


def cmd_job(args) -> int:
    params, extra, payload = {}, None, None
    if args.kind == "remove":
        params, extra = _plan_remove(args)
    elif args.kind == "install":
        params, extra, payload = _plan_install(args)
    elif args.kind == "undo":
        params, extra = _plan_undo(args)
    elif args.kind == "autokit-config":
        if args.restore:
            Store().job(args.serial, args.restore)  # must be a known job
            params = {"restore": args.restore}
        else:
            if args.lang is None or args.screen is not None or args.decoder is not None:
                params = {"screen": args.screen or "800,480,15", "decoder": args.decoder or "software"}
            if args.lang is not None:  # four bytes, so the file travels in the job folder
                params["lang"] = args.lang
                extra = {"lang": autokit_lang_file(AUTOKIT_LANGS[args.lang])}
    elif args.kind == "logger":
        params = {"seconds": args.seconds, "native": args.native}
        extra = {"s2amwatch.exe": native.binary("s2amwatch.exe")}
        if args.native:
            extra["notifylog.exe"] = native.binary("notifylog.exe")
        print(f"logger: insert the stick and leave it in; for {args.seconds} s it records every "
              f"program and window on the screen. Do the test meanwhile, then import it")
    elif args.kind == "native-hello":
        extra = {"hello.exe": native.binary("hello.exe")}
    elif args.kind == "runner-guard":
        stock = (args.upstream / "FullPack/SyncExtendedPack/Apps/Tools/SyncAppsRunner.exe").stat().st_size
        params = {"action": "disable" if args.off else "enable", "stock_size": stock}
        if not args.off:
            extra = {"s2amrun.exe": native.binary("s2amrun.exe")}
            if len(extra["s2amrun.exe"]) == stock:  # the job tells them apart by size
                raise ValueError("the guard is exactly the size of the stock runner; change s2amrun.c")
    if getattr(args, "dry_run", False):
        return 0
    job = Job(serial=args.serial, kind=JOB_KINDS[args.kind], params=params)
    workdir = Path(args.work or REPO / "build" / "jobs" / job.id).resolve()
    stage(job, args.upstream, workdir, extra, payload)
    if job.kind == "inst" and params["app"].lower() == "autokit":
        autokit.patch_folder(workdir / "payload" / "SyncExtendedPack/Apps/Media/AutoKit",
                             args.upstream / autokit.HOOK_SOURCE)
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
    if job.kind == "log":
        seconds = job.params.get("seconds", 180)
        print(f"in the car: insert the stick and LEAVE IT IN. After 'Install successfully completed' "
              f"the logger records for {seconds} s: do the test meanwhile. Leave the stick in "
              f"even if you have to restart SYNC; pull it afterwards")
    else:
        print("in the car: insert the stick, wait for 'Install successfully completed', pull it")
    if job.kind in apps.MENU_KINDS:
        print("SYNC restarts after this job")
    _eject(Path(args.stick), args)
    return 0


def cmd_stick_import(args) -> int:
    results = stick.import_reports(Path(args.stick), Store(), require_volume=not args.any_path)
    if not results:
        print("no s2am jobs on this stick")
    store = Store()
    for record in results:
        note = " (stick was inserted again; nothing ran twice)" if record.get("replayed") else ""
        reason = f" ({record['reason']})" if record.get("reason") else ""
        print(f"{record['id']}: {record['status']}{note}{reason}{STOP_HINTS.get(record['status'], '')}")
        report = store.report(record.get("serial", ""), record["id"]) if record.get("serial") else None
        if report and (report / "mount-check.txt").is_file():
            print("  warning: " + (report / "mount-check.txt").read_text(errors="replace").strip()
                  + " (use one stick, always in the same USB port)")
        if record.get("kind") == "hello" and record["status"] == "applied":
            hello = report / "native-hello.txt" if report else None
            text = hello.read_text(errors="replace").strip() if hello and hello.is_file() else ""
            print(f"  verified: native code runs on this SYNC 2 ({text.split('|')[1]})"
                  if text.startswith("s2am native hello ok") and "|" in text else
                  "  NOT verified: hello.exe wrote nothing; native code may not run here")
        if record.get("kind") == "guard" and record["status"] == "applied":
            print(f"  {_verify_guard(store, record)}")
        if record.get("kind") in apps.MENU_KINDS and record["status"] == "applied":
            verdict = _verify_menu(store, record)
            print(f"  {verdict}")
            if record["kind"] == "undo" and verdict.startswith("verified"):
                target = store.job(record["serial"], record["params"]["target"])
                store.save_job(record["serial"], target["id"], {**target, "undone_by": record["id"]})
    return 0 if all(r["status"] in ("applied", "already-applied", "pending") for r in results) else 1


STOP_HINTS = {
    "stale": ": the car's menu changed since the job was planned. Nothing changed; run an "
             "inventory, then plan again",
    "busy": ": the app was running and nothing changed. UpdateService used up the stick anyway: "
            "restart SYNC, run `s2am stick prepare` with the same job again, then insert it",
    "failed": ": the job stopped before deleting anything; its report says why "
              "(copy-failed means the old menu was put back)",
}


def _guard_on(entries) -> bool:
    return any(e.path.lower().endswith("\\tools\\syncappsrunner.orig.exe") for e in entries)


def _verify_guard(store: Store, record: dict) -> str:
    """Check the runner guard's state after a runner-guard job, from its own report."""
    report = store.report(record["serial"], record["id"])
    inventory = report / "inventory.txt" if report else None
    if not inventory or not inventory.is_file():
        return "not verified: the report has no inventory"
    on = _guard_on(parse_inventory(inventory.read_text(errors="replace")))
    if record["params"].get("action") == "enable":
        selftest = report / "guard-selftest.txt"
        seen = selftest.read_text(errors="replace").strip() if selftest.is_file() else "none"
        return (f"verified: runner guard is on (self-test: {seen})" if on else
                "NOT verified: the original runner was not kept, so the guard is not on")
    return "verified: runner guard is off" if not on else "NOT verified: the guard is still on"


def _verify_menu(store: Store, record: dict) -> str:
    """Check the car's menu after a remove/undo job against what the job set out to do."""
    report = store.report(record["serial"], record["id"])
    xml = report / "SyncApps.xml" if report else None
    if not xml or not xml.is_file():
        return "not verified: the report has no SyncApps.xml"
    names = [name.lower() for name, _, _ in apps.menu_entries(xml.read_bytes()) if name]
    app = record.get("params", {}).get("app", "")
    listed = record.get("params", {}).get("apps") or [app]
    present = all(name.lower() in names for name in listed)
    if record["kind"] == "rm":
        still = [name for name in listed if name.lower() in names]
        verb = "is" if len(listed) == 1 else "are"
        return f"verified: {app!r} {verb} no longer in the menu" if not still else \
            f"NOT verified: {still} still in the menu"
    if record["kind"] == "inst":
        inventory = report / "inventory.txt"
        listed = {e.path.replace("\\", "/").lower() for e in parse_inventory(
            inventory.read_text(errors="replace"))} if inventory.is_file() else set()
        folders = [f for f in record["params"].get("files", []) if f.endswith("/")]
        missing = [f for f in folders if f.rstrip("/").lower() not in listed]
        if not present or missing:
            return f"NOT verified: in menu={present}, folders missing from the report: {missing}"
        return f"verified: {app!r} is in the menu and its files are on the car"
    return f"verified: {app!r} is back in the menu" if present else \
        f"NOT verified: {app!r} is not in the menu"


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
    print(f"  AutoKit video: {autokit_settings(store.report(args.serial, job_id), entries)}")
    print(f"  runner guard (fixes the freeze when leaving an app): "
          f"{'on' if _guard_on(entries) else 'off'}")
    guard_log = store.report(args.serial, job_id) / "guard.log"
    if guard_log.is_file():
        lines = guard_log.read_text(errors="replace").strip().splitlines()
        print("  guard log (last 8 lines):")
        for line in lines[-8:]:
            print(f"    {line}")
    return 0


def autokit_settings(report: Path, entries) -> str:
    """screenconfig and decoder from the last report (the decoder is the usehwdec flag file)."""
    names = {e.path.lower() for e in entries if e.kind == "F"}
    if f"{AUTOKIT_CE}\\autokit.exe".lower() not in names:
        return "AutoKit not installed"
    config = report / "autokit-screenconfig.txt"
    screen = config.read_text(errors="replace").strip() if config.is_file() else "default (800,480,15)"
    hardware = f"{AUTOKIT_CE}\\usehwdec".lower() in names
    lang = report / "autokit-lang.bin"
    lcid = int.from_bytes(lang.read_bytes()[:4], "little") if lang.is_file() else None
    names_by_id = {v: k for k, v in AUTOKIT_LANGS.items()}
    language = names_by_id.get(lcid, f"0x{lcid:04x}") if lcid is not None else "unknown"
    return f"screen {screen}, decoder {'hardware' if hardware else 'software'}, language {language}"


def _registry_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        kind, _, rest = line.partition("|")
        if kind == "K":
            out.append(rest)
        elif kind == "V":
            key, _, value = rest.partition("|")
            out.append(f"    {value}")
        elif kind == "S":
            out.append(f"system: {rest.partition('|')[2]}")
    return out


def _log_changes(text: str) -> list[str]:
    """The logger's lines, keeping only those where something changed."""
    out, previous = [], None
    for line in text.splitlines():
        stamp, _, state = line.partition("|")
        if line.startswith(("start", "end")) or state != previous:
            out.append(line)
            previous = state
    return out


def cmd_native(args) -> int:
    for name, path in native.build().items():
        print(f"{name}: {path.stat().st_size} B, sha256 {pack.sha256(path)[:16]}, WinCE ARM, COREDLL only")
    return 0


def cmd_report(args) -> int:
    store = Store()
    job_id = args.job_id or next((r["id"] for r in reversed(store.jobs(args.serial))
                                  if store.report(args.serial, r["id"])), None)
    report = store.report(args.serial, job_id) if job_id else None
    if report is None:
        print("no imported report", file=sys.stderr)
        return 1
    print(f"report {job_id}")
    for name in ("info.txt", "busy.txt", "stale.txt", "firmware-image-removed.txt",
                 "native-hello.txt", "guard-selftest.txt", "selftest-failed.txt"):
        if (report / name).is_file():
            print(f"[{name}] " + (report / name).read_text(errors="replace").strip().replace("\r\n", "; "))
    if (report / "registry.txt").is_file():
        print("[registry]")
        print("\n".join(_registry_lines((report / "registry.txt").read_text(errors="replace"))))
    if (report / "notify.txt").is_file():
        print("[notify: ms since start|kind|...] AutoKit window messages and foreground changes")
        print((report / "notify.txt").read_text(errors="replace").rstrip())
    if (report / "log.txt").is_file():
        print("[log: time|AutoKit running|foreground process|window|USB devices], changes only")
        print("\n".join(_log_changes((report / "log.txt").read_text(errors="replace"))))
    if (report / "watch.log").is_file():
        print("[watch.log: time|event|details] processes, windows top to bottom, SYNC shown or "
              "hidden, whether AutoKit answers; changes only")
        print((report / "watch.log").read_text(errors="replace").rstrip())
    for name, title in (("guard.log", "runner guard log when the stick ran"),
                        ("guard-live.log", "runner guard log, last copy the watcher made"),
                        ("autokit-hwlog.log", "AutoKit's own log when the stick ran"),
                        ("autokit-hwlog-live.log", "AutoKit's own log, last copy the watcher made")):
        if (report / name).is_file():
            print(f"[{name}: {title}]")
            print((report / name).read_text(errors="replace").rstrip())
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
    sub.add_parser("wizard", help="guided install for everyone: plain questions, one car "
                   "trip at a time").set_defaults(func=cmd_wizard)

    boot = sub.add_parser("bootstrap", help="first SyncExtPack install")
    boot_sub = boot.add_subparsers(dest="action", required=True)
    boot_prepare = boot_sub.add_parser("prepare")
    boot_prepare.add_argument("--serial", type=_serial, required=True)
    boot_prepare.add_argument("--stick", required=True)
    boot_prepare.add_argument("--manifest", help="use an existing make_pack manifest instead of building")
    boot_prepare.add_argument("--apps-only", action="store_true",
                              help="the car already runs job sticks (UpdateService is there): "
                                   "put only the app pack on the stick, as install.bin")
    boot_finish = boot_sub.add_parser("finish")
    boot_finish.add_argument("stick")
    for command, func in ((boot_prepare, cmd_bootstrap_prepare), (boot_finish, cmd_bootstrap_finish)):
        command.add_argument("--any-path", action="store_true",
                             help="allow a folder outside /Volumes; skips disk checks and eject")
        command.add_argument("--no-eject", action="store_true")
        command.set_defaults(func=func, force=False)
    boot_prepare.add_argument("--force", action="store_true",
                              help="accept a failed stick check, a near window boundary, or old files")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--serial", type=_serial, required=True)
    common.add_argument("--upstream", type=Path, default=UPSTREAM)
    common.add_argument("--work", help="staging folder (default build/jobs/<id>)")
    common.add_argument("--no-pack", action="store_true", help="stage only, skip crypto_pack")
    common.add_argument("--force", action="store_true", help="build even near a window boundary")
    job = sub.add_parser("job", help="build a job")
    job_sub = job.add_subparsers(dest="kind", required=True)
    for name, help_text in (("inventory", "list installed apps and the menu"),
                            ("autokit-stock", "swap AutoKit to its stock audio modules"),
                            ("autokit-patched", "swap AutoKit to the patched audio modules")):
        job_sub.add_parser(name, parents=[common], help=help_text).set_defaults(func=cmd_job)
    remove = job_sub.add_parser("remove", parents=[common],
                                help="take an app out of the Apps menu (--purge deletes its files)")
    remove.add_argument("app", nargs="+",
                        help="the names shown in the Apps menu (see s2am status); several go in one job")
    remove.add_argument("--purge", action="store_true", help="also delete the app's files")
    remove.add_argument("--dry-run", action="store_true", help="show the plan, build nothing")
    remove.set_defaults(func=cmd_job)
    config = job_sub.add_parser("autokit-config", parents=[common],
                                help="set AutoKit's video size and decoder (Android Auto picture)")
    config.add_argument("--screen", help="width,height,fps (default 800,480,15)")
    config.add_argument("--decoder", choices=["software", "hardware"], help="default software")
    config.add_argument("--lang", choices=sorted(AUTOKIT_LANGS),
                        help="AutoKit's own language (the stock folder is Chinese); "
                             "on its own it leaves the video settings alone")
    config.add_argument("--restore", metavar="JOB_ID", help="put back what that config job replaced")
    config.set_defaults(func=cmd_job)
    job_sub.add_parser("snapshot", parents=[common],
                       help="read-only: services, startup entries and USB devices").set_defaults(func=cmd_job)
    logger = job_sub.add_parser("logger", parents=[common],
                                help="record every program and window on the screen, twice a second")
    logger.add_argument("--seconds", type=int, default=180)
    logger.add_argument("--native", action="store_true",
                        help="also run notifylog.exe, which records AutoKit's window messages")
    logger.set_defaults(func=cmd_job)
    job_sub.add_parser("native-hello", parents=[common],
                       help="prove compiled code runs on this SYNC 2").set_defaults(func=cmd_job)
    guard = job_sub.add_parser("runner-guard", parents=[common],
                               help="stop the frozen screen after leaving an app (keeps Ford's "
                                    "runner for --off)")
    guard.add_argument("--off", action="store_true", help="put the original runner back")
    guard.set_defaults(func=cmd_job)
    install = job_sub.add_parser("install", parents=[common],
                                 help="copy a SyncExtPack app to the car and add it to the menu")
    install.add_argument("app", help="the app name (see s2am apps)")
    install.add_argument("--variant", help="SyncExtPack unit to install (see s2am apps)")
    install.add_argument("--reinstall", action="store_true",
                         help="the app is already in the menu: overwrite its files (update)")
    install.add_argument("--dry-run", action="store_true", help="show the plan, build nothing")
    install.set_defaults(func=cmd_job)
    native_cmd = sub.add_parser("native", help="build the native WinCE helpers (CeGCC in Docker)")
    native_cmd.add_argument("action", choices=["build"])
    native_cmd.set_defaults(func=cmd_native)
    show = sub.add_parser("report", help="print a report: info, registry snapshot, logger timeline")
    show.add_argument("--serial", type=_serial, required=True)
    show.add_argument("job_id", nargs="?", help="default: the newest report")
    show.set_defaults(func=cmd_report)
    listing = sub.add_parser("apps", help="installable apps and what the last report shows")
    listing.add_argument("--serial", type=_serial, required=True)
    listing.add_argument("--upstream", type=Path, default=UPSTREAM)
    listing.set_defaults(func=cmd_apps)
    undo = job_sub.add_parser("undo", parents=[common], help="put a removed app back in the menu")
    undo.add_argument("job_id", help="the remove job to undo")
    undo.set_defaults(func=cmd_job)

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
    prepare.add_argument("--no-eject", action="store_true")
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
    except (pack.PackError, stick.StickError, bootstrap.BootstrapError, apps.AppError, autokit.PatchFailed,
            native.NativeError,
            ContainerError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"s2am: {error}", file=sys.stderr)
        return 1
