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
    s2am job logger --load --serial S            measure the processor's load, per program and thread
    s2am job logger --collect JOB_ID --serial S  fetch that measurement from the car
    s2am report --serial S [JOB_ID]              print a report (snapshot, logger timeline)
    s2am native build                            build the WinCE helpers (CeGCC in Docker)
    s2am job native-hello --serial S             prove compiled code runs on this SYNC 2
    s2am job runner-guard --serial S [--off]     fix the frozen screen after leaving an app
    s2am job runner-guard --boost 251|off ...    more processor for CarPlay's video (optional, untried)
    s2am job decoder --from FOLDER --serial S    AutoKit's video decoder files swapped (untried); --restore JOB
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

from . import apps, autokit, bootstrap, decoder, diskcheck, native, pack, stick, theme, window
from .container import REPO, ContainerError
from .job import (AUTOKIT_CE, AUTOKIT_LANGS, AUTOKIT_MODULES, BOOST_LEVELS, DRIVE_SECONDS, LOAD_SECONDS,
                  CLOCK_ROOTS, REGISTRY_ROOTS, RESTARTING,
                  SCREENS, SERIAL, STARTUP_SCREENS, SWAP_KINDS, Job, autokit_lang_file, bundle_parts, stage)
from .state import VERDICTS, Store, diff, outcome, parse_inventory

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
             "snapshot": "snap", "logger": "log", "native-hello": "hello", "runner-guard": "guard",
             "theme": "theme", "apps-menu": "appmenu", "cleanup": "clean", "screen": "screen",
             "bundle": "bundle", "registry": "reg", "decoder": "dec", "pmic": "pmic", "clock": "clock",
             "decoder-inspect": "decdiag"}
MARK = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}


def _eject(stick_path: Path, args) -> None:
    if args.no_eject or args.any_path:
        return
    result = subprocess.run(["diskutil", "eject", str(stick_path)], capture_output=True, text=True)
    print("stick ejected" if result.returncode == 0 else
          f"eject failed, eject it in Finder before pulling it: {result.stderr.strip()}")


def _remount(stick_path: Path) -> bool:
    """Unmount and mount the stick again, so it is read from the stick, not from the Mac's cache."""
    info = subprocess.run(["diskutil", "info", str(stick_path)], capture_output=True, text=True).stdout
    device = next((line.split(":", 1)[1].strip() for line in info.splitlines()
                   if line.strip().startswith("Device Identifier:")), None)
    if not device:
        return False
    for _ in range(5):  # Spotlight may hold it for a moment
        if subprocess.run(["diskutil", "unmount", str(stick_path)], capture_output=True).returncode == 0:
            break
        subprocess.run(["sleep", "2"])
    else:
        return False
    return subprocess.run(["diskutil", "mount", device], capture_output=True).returncode == 0 and stick_path.is_dir()


def _read_back(stick_path: Path, install: Path, job: Job, args) -> bool:
    """Read the stick back (after a remount, unless --any-path or --no-eject) before it is ejected."""
    remounted = False if args.no_eject or args.any_path else _remount(stick_path)
    wrong = stick.differences(stick_path, install, job)
    if wrong:
        print(f"FAIL: {', '.join(wrong)} did not read back as written. Do not use this stick: prepare it again, "
              "or use another")
        return False
    print("read back: identical" + (" after a remount" if remounted else ""))
    return True


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


RUNNER_FILES = ("MortScript.exe", "s2amjob.exe", "s2amjob.mscr")  # each part's own; the bundle has its


def _plan_bundle(store: Store, serial: str, folders: list[Path]) -> tuple[dict, list[tuple[Path, str]]]:
    """(params, payload) for a bundle of jobs already built, read from their job folders: each
    part's plan, and its files (checked against the hashes it was built with) at its own car path."""
    parts, payload = [], []
    for folder in folders:
        job = Job.from_json((folder / "job.json").read_text())
        if job.serial != serial or job.kind == "bundle":
            raise ValueError(f"{folder} is not a job for {serial} that a bundle can hold")
        try:
            status = store.job(serial, job.id).get("status")
        except (OSError, ValueError, KeyError):
            status = None
        if status in ("applied", "already-applied"):
            raise ValueError(f"{job.id} has run on the car already")
        if status is not None:  # built on this Mac: the folder must hold exactly what was recorded
            record = store.job(serial, job.id)
            if (record.get("params"), record.get("files")) != (job.params, job.files):
                raise ValueError(f"{folder}/job.json is not what {job.id} was built as")
        for car_path, digest in job.files.items():
            name = car_path[len(job.job_dir) + 1:] if car_path.startswith(job.job_dir + "/") else ""
            if not name or "/" in name or "\\" in name or name.startswith("."):
                raise ValueError(f"{job.id} lists a file outside its own folder: {car_path}")
            source = folder / "payload" / car_path.lstrip("/")
            if not source.is_file() or pack.sha256(source) != digest:
                raise ValueError(f"{source} is not the file {job.id} was built with")
            if Path(car_path).name not in RUNNER_FILES:
                payload.append((source, car_path))
        parts.append({"kind": job.kind, "id": job.id, "created_utc": job.created_utc, "params": job.params})
    params = {"parts": parts}
    bundle_parts(Job(serial, "bundle", params=params))  # kinds, order, no repeats
    return params, payload


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
        if args.measure is not None:  # the watcher and the load logger travel in the job folder
            params["measure"] = args.measure
            extra = {**(extra or {}), "s2amwatch.exe": native.binary("s2amwatch.exe"),
                     "s2amdrive.exe": native.binary("s2amdrive.exe")}
            print(f"measure: once the settings are in place it records the processor's load, clock and "
                  f"core voltage for {args.measure} s, on the car. Insert the same stick again to fetch the logs")
    elif args.kind == "logger" and args.collect:
        measured = Store().job(args.serial, args.collect).get("params", {})
        if not measured.get("load") and not measured.get("measure"):
            raise ValueError(f"{args.collect} is not a logger --load job")
        params = {"collect": args.collect}
        print(f"collect: copies what {args.collect} wrote on the car to the stick")
    elif args.kind == "logger":
        seconds = args.seconds or (DRIVE_SECONDS if args.drive else LOAD_SECONDS if args.load else 180)
        params = {"seconds": seconds, "native": args.native}
        extra = {"s2amwatch.exe": native.binary("s2amwatch.exe")}
        if args.native:
            extra["notifylog.exe"] = native.binary("notifylog.exe")
        if args.drive:
            params["drive"] = True
            extra["s2amdrive.exe"] = native.binary("s2amdrive.exe")
            print(f"drive logger: insert the stick and leave it in while you drive; for up to {seconds} s "
                  "it records the screens (screenshots), processor load, every file's name and a copy "
                  "of Ford's screen files. Pull the stick when you are done, then import it")
        elif args.load:
            params["load"] = True
            extra["s2amdrive.exe"] = native.binary("s2amdrive.exe")
            print(f"load logger: for {seconds} s it records the processor's load per program and thread, "
                  "and nothing else, on the car, so the stick can leave. Build the second stick "
                  "as well: s2am job logger --collect <this job>")
        else:
            print(f"logger: insert the stick and leave it in; for {seconds} s it records every "
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
        if args.boost == "off":
            params["boost"] = 0
            print("boost off: the guard stays on; the app's threads keep the priorities it gives them")
        elif args.boost:
            params["boost"] = int(args.boost)
            where = {251: "still below Ford's screens (250)", 250: "level with Ford's screens (250)"}
            print(f"boost {args.boost}: while the app is alone on the screen, its threads at priority 252 "
                  f"(AutoKit's video) run at {args.boost}, {where[params['boost']]}. Test calls, climate "
                  "and the parking sensors with CarPlay open. Undo: --boost off (or --off for the whole guard)")
    elif args.kind == "theme":
        params, extra = theme.plan(Store(), args.serial, args.preset, args.source, args.restore, args.fetch)
        if params.get("restore"):
            print(f"theme: puts back what {args.restore} replaced ({', '.join(params['files'])}); SYNC restarts")
        else:
            print(f"theme: replaces {', '.join(params['files'])} in {theme.THEMES_CE}, backing them up first; "
                  "SYNC restarts. Build the restore stick now as well: s2am job theme --restore <this job>")
        if params.get("fetch"):
            print(f"  and copies {len(params['fetch'])} car files to the stick for study (read-only)")
    elif args.kind == "apps-menu":
        params, extra = theme.plan_menu(Store(), args.serial, args.swf, args.tiles, args.restore, args.fetch)
        if params.get("restore"):
            print(f"apps-menu: puts SyncExtPack's own Apps menu back (what {args.restore} replaced); "
                  "the tile pictures stay, unused; SYNC restarts")
        else:
            print(f"apps-menu: replaces SyncApps.swf and adds {len(params['added'])} tile pictures, backing up "
                  "the menu first; SYNC restarts. Build the restore stick now as well: "
                  "s2am job apps-menu --restore <this job>")
    elif args.kind == "pmic":
        extra = {"s2ampmic.exe": native.binary("s2ampmic.exe")}
        print("pmic: reads identification, SW1 voltage presets and mode/SID configuration through PMI1. "
              "The new mode read is untested in the car. No voltage or clock changes. Presets do not identify "
              "the active rail voltage. Leave the stick in until 'Install successfully completed', "
              "then import it; check pmic.txt for the result")
    elif args.kind == "clock" and args.modules:
        params = {"modules": True}
        extra = {name: native.binary(name) for name in ("s2ampmic.exe", "s2ammodules.exe")}
        print("clock modules: reads PMIC presets and mode/SID configuration; records attributes and "
              "ordinary-file copy results for eight fixed clock/power modules. ROM modules are metadata-only. "
              "No frequency/voltage change, DLL loading or restart. New helpers need car validation. "
              "Leave the stick in until 'Install successfully completed', then import both reports")
    elif args.kind in ("registry", "clock"):
        params = {"roots": args.root or list(REGISTRY_ROOTS), "depth": args.depth}
        if args.fetch:
            params["fetch"] = theme.fetch_list(Store(), args.serial, args.fetch)
        extra = {"s2amreg.exe": native.binary("s2amreg.exe")}
        if args.kind == "clock":
            extra["s2ampmic.exe"] = native.binary("s2ampmic.exe")
            print("clock: also reads MC13892 identification, SW1 presets and mode/SID through PMI1 first. "
                  "No clock/voltage changes or restart. Presets are not active-voltage measurements; "
                  "the new mode read and any frequency-control interface remain unverified")
        print(f"registry: read-only; copies {', '.join(params['roots'])} ({args.depth} levels) to the stick. "
              "A paired phone's link key and PINs are not copied. Insert and leave it in until 'Install "
              "successfully completed': the screen may stay at 100% for several minutes. "
              "The script's wait limits do not bound blocked driver calls. Then pull it and import it")
        if params.get("fetch"):
            print(f"  and copies {len(params['fetch'])} car files to the stick for study (read-only)")
    elif args.kind == "bundle":
        params, payload = _plan_bundle(Store(), args.serial, args.part)
        print(f"bundle: {len(params['parts'])} jobs in one run, in this order, each verified on its own "
              "after import; the first that stops ends the run:")
        for part in params["parts"]:
            print(f"  {part['id']}")
        print("SYNC restarts after it")
    elif args.kind == "screen":
        params, extra = theme.plan_screen(Store(), args.serial, args.screen, args.swf, args.restore, args.fetch,
                                          args.startup)
        if params.get("restore"):
            print(f"screen: puts Ford's own {params['screen']} back (what {args.restore} replaced); SYNC restarts")
        else:
            print(f"screen: replaces Ford's {params['screen']}, backing it up first; SYNC restarts. "
                  "Build the restore stick now as well: s2am job screen --restore <this job>")
            if params["screen"] in STARTUP_SCREENS:
                print("  this screen loads when SYNC starts: if the screen stays dark afterwards, insert the "
                      "undo stick anyway and wait two minutes (RECOVERY.md)")
    elif args.kind == "decoder-inspect":
        from . import decoder_inspect
        params = decoder_inspect.plan(Store().job(args.serial, args.target))
        extra = {name: native.binary(name) for name in ("s2amdiag.exe", "s2amclock.exe")}
        print("decoder inspection: native startup, active/backup/staged file evidence and a fresh harmless "
              "script probe. The separate clock probe attempts fixed register reads through ceddk; "
              "mapping may be denied. No decoder replacement, clock/voltage writes or reboot.")
    elif args.kind == "decoder":
        params, extra = decoder.plan(Store(), args.serial, args.upstream, args.source, args.restore)
        if params.get("restore"):
            print(f"decoder: puts AutoKit's own three decoder files back (what {args.restore} replaced). "
                  "SYNC does not restart")
        else:
            print(f"decoder: replaces AutoKit's three decoder files ({', '.join(params['files'])}), backing "
                  "them up first. SYNC does not restart. Build the undo stick now, at the same time: "
                  "s2am job decoder --restore <this job>")
            print("  if a run is cut short (the stick pulled, the power lost), AutoKit may not start until "
                  "the undo stick has run")
        print("  AutoKit must not be running, and it keeps running hidden after its Exit button: restart "
              "SYNC and insert the stick before opening AutoKit")
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
    try:  # the byte check of its run, and its last outcome, stay with the job: the car runs it only once
        stored = Store().job(job.serial, job.id)
        checked = {**{key: value for key, value in stored.items() if key in VERDICTS}, **outcome(stored)}
    except (OSError, ValueError):
        checked = {}
    Store().save_job(job.serial, job.id, _record(job, "on-stick", **checked))
    print(f"job {job.id} is on {args.stick}")
    if archive.exists():
        print(f"earlier UpdateService files moved to {archive}")
    if job.kind == "log" and job.params.get("drive"):
        print("in the car: insert the stick and LEAVE IT IN. After 'Install successfully completed' "
              "drive and use SYNC as usual (screens change only when parked or by a passenger). "
              "Pull the stick when you are done; the logger stops by itself after "
              f"{job.params.get('seconds', DRIVE_SECONDS)} s")
    elif job.kind == "akcfg" and job.params.get("measure"):
        print("in the car: Exit AutoKit, insert the stick, wait for 'Install successfully completed', pull "
              f"it. It measures for {job.params['measure']} s, writing to the car. Insert the same stick "
              "once more at the end, and wait for the same message: that fetches the logs")
    elif job.kind == "log" and job.params.get("load"):
        print("in the car: insert the stick, wait for 'Install successfully completed', pull it. The "
              f"logger writes to the car for {job.params.get('seconds', LOAD_SECONDS)} s, so its port "
              "is free for the adapter. A logger --collect stick fetches the logs afterwards")
    elif job.kind == "log" and not job.params.get("collect"):
        seconds = job.params.get("seconds", 180)
        print(f"in the car: insert the stick and LEAVE IT IN. After 'Install successfully completed' "
              f"the logger records for {seconds} s: do the test meanwhile. Leave the stick in "
              f"even if you have to restart SYNC; pull it afterwards")
    elif job.kind == "dec":
        print("in the car: restart SYNC and do not open AutoKit (its Exit button only hides it). Insert the "
              "stick, wait for 'Install successfully completed', pull it, then open AutoKit")
    else:
        print("in the car: insert the stick, wait for 'Install successfully completed', pull it")
    if job.kind in RESTARTING:
        print("SYNC restarts after this job")
    if not _read_back(Path(args.stick), install, job, args):
        return 1
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
        report = store.report(record.get("serial", ""), record["id"]) if record.get("serial") else None
        verdict = _byte_check(store, record, report)
        print(f"{record['id']}: {record['status']}{note}{reason}{_hint(record)}")
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
        if record.get("kind") == "clean" and record["status"] == "applied" and report and not record.get("replayed"):
            listed = (report / "cleanup.txt").read_text(errors="replace").splitlines() \
                if (report / "cleanup.txt").is_file() else []
            gone, stuck = sum(x.startswith("D|") for x in listed), [x[2:] for x in listed if x.startswith("S|")]
            print(f"  removed {gone} old job folders" + (f"; still there: {stuck}" if stuck else ""))
        if record.get("kind") in ("reg", "clock") and record["status"] == "applied" and report \
                and not (record.get("kind") == "clock" and record.get("params", {}).get("modules") is True):
            done = report / "registry-done.txt"
            print("  " + (done.read_text(errors="replace").strip().replace("|", ", ") if done.is_file() else
                          "NOT complete: s2amreg.exe did not finish in time; registry.txt may be partial"))
        if record.get("kind") in ("pmic", "clock") and record["status"] == "applied" and report:
            from . import pmic
            print("  " + pmic.summary(report))
        if record.get("kind") == "clock" and record.get("params", {}).get("modules") is True \
                and record["status"] == "applied" and report:
            from . import modules
            print("  " + modules.summary(report))
        if record.get("kind") == "decdiag" and report:
            from . import clock_snapshot, decoder_inspect
            inspected = Job.from_json(json.dumps(record))
            print("  " + decoder_inspect.summary(report, inspected))
            evidence = decoder_inspect.analyze(report, inspected)
            if evidence["complete"]:
                print("  " + clock_snapshot.summary(report / "clock.txt", evidence["processes"]["C"]))
        if verdict:
            print(f"  {verdict}")
        if record.get("kind") in apps.MENU_KINDS and record["status"] == "applied":
            verdict = _verify_menu(store, record)
            print(f"  {verdict}")
            if record["kind"] == "undo" and verdict.startswith("verified"):
                target = store.job(record["serial"], record["params"]["target"])
                store.save_job(record["serial"], target["id"], {**target, "undone_by": record["id"]})
    return 0 if all(r["status"] in ("applied", "already-applied", "pending") for r in results) else 1


STOP_HINTS = {
    "stopped": ": one of its parts stopped before changing anything more; the lines below say "
               "which and why. Parts before it are on the car",
    "not-run": ": an earlier part of its bundle stopped, so this one did not run",
    "interrupted": ": it started but did not finish (power cut or stick pulled). Run the undo stick",
    "not-verified": ": the files on the car do not match byte for byte (below). Run the undo stick",
    "stale": ": the car's files changed since the job was planned. Nothing changed; run an "
             "inventory (or a drive log, for a theme), then plan again",
    "busy": ": the app was running, so this run changed nothing. UpdateService used up the stick anyway: "
            "restart SYNC, run `s2am stick prepare` with the same job again, then insert it",
    "rollback-failed": ": the car may have a damaged file; use the undo (restore) stick now; "
                       "if the screen stays dark, insert it anyway and wait two minutes",
    "failed": ": the job stopped; its report says why (if a restore did not complete, prepare the "
              "restore stick again with `s2am stick prepare` and the same restore job, then insert it)",
}
SWAP_COMMANDS = {kind: name for name, kind in JOB_KINDS.items() if kind in SWAP_KINDS}


def _byte_check(store: Store, record: dict, report: Path | None) -> str | None:
    """The Mac's byte check of a swap job's files on the car, from its report; returns the line
    to print. The car checks sizes only, and a copy can go wrong at full length.

    A job that ran to the end is checked from what its run copied to the stick (applied/ and
    backup/; each run deletes an earlier run's first, job.READBACK). A replay ran nothing: one
    already checked keeps that check (state.VERDICTS) and says nothing new; one not yet checked, or
    not successfully, is checked from its first run's copy on this stick if that run finished here
    (done.txt, so "applied"). Otherwise (a replay from another stick, or of a run cut short on this
    one, whose copies the finished run may not match) it keeps a failed check or, without any,
    reads as not verified: nothing shows what the car holds. After a failed copy, what the rollback
    put back (rolledback/) is checked against the originals. A failed check makes the job
    "not-verified" and stays with it until a later check of the same job succeeds.
    """
    if record.get("kind") not in SWAP_KINDS:
        return None
    status, params, kept = record["status"], record["params"], record.get("verified") or record.get("not_verified")
    replayed, earlier = record.get("replayed"), False
    if status in ("applied", "already-applied"):
        if replayed and record.get("verified"):
            return None  # checked at an earlier import; nothing ran now
        if report is not None and status == "applied":  # the run that finished, on this stick
            verdict = theme.verify(report, params, record["kind"])
        elif kept:
            verdict, earlier = kept, True
        else:
            verdict = ("NOT verified: this stick holds no copy from the run that finished the job (it ran from "
                       "another stick, or was cut short on this one), so nothing shows that the car has the "
                       "planned files")
    elif status == "failed" and report is not None and (report / "copy-failed.txt").is_file() \
            and not params.get("restore"):
        verdict = theme.verify_rollback(report, params)
    else:  # it did not get far enough this time to show anything: an earlier check still stands
        return f"its last byte check, at an earlier import: {kept}" if kept else None
    good = verdict.startswith("verified")
    if not good:
        record["status"] = "not-verified"
    for key in VERDICTS:
        record.pop(key, None)
    record["verified" if good else "not_verified"] = verdict
    stored = {key: value for key, value in store.job(record["serial"], record["id"]).items() if key not in VERDICTS}
    store.save_job(record["serial"], record["id"], {**stored, "status": record["status"],
                                                    "outcome": record["status"],  # what this import found
                                                    "verified" if good else "not_verified": verdict})
    return verdict + (" (from an earlier import)" if earlier else "")


def _hint(record: dict) -> str:
    """STOP_HINTS for the record's status, in the words of its own job where they differ: a swap
    job's undo is a restore job built from it, and a restore that did not finish runs again from
    a stick prepared again (UpdateService has used up the one it ran from)."""
    status, kind, params = record["status"], record.get("kind"), record.get("params") or {}
    if kind not in SWAP_COMMANDS or status not in ("interrupted", "not-verified", "rollback-failed"):
        return STOP_HINTS.get(status, "")
    autokit = "; AutoKit may not start until it has run" if kind == "dec" else ""
    if params.get("restore") and status == "not-verified":  # it ran to the end: the car counts it as done
        return (f": the original files are not all back. Build the restore again (a new job) with "
                f"`s2am job {SWAP_COMMANDS[kind]} --restore {params['restore']}` and insert its stick{autokit}")
    if params.get("restore"):
        return (": the original files may not all be back. Prepare this restore stick again with "
                f"`s2am stick prepare` and the same job ({record['id']}), then insert it{autokit}")
    return (f"{STOP_HINTS[status]}. Build it with `s2am job {SWAP_COMMANDS[kind]} --restore {record['id']}`"
            f"{autokit}")


def _guard_on(entries) -> bool:
    return any(e.path.lower().endswith("\\tools\\syncappsrunner.orig.exe") for e in entries)


def _guard_boost(report: Path | None) -> str | None:
    """What the car's boost file held when the report was written (every inventory copies it)."""
    path = report / "guard-boost.txt" if report else None
    return path.read_text(errors="replace").strip() if path and path.is_file() else None


def _verify_guard(store: Store, record: dict) -> str:
    """Check the runner guard's state after a runner-guard job, from its own report."""
    report = store.report(record["serial"], record["id"])
    inventory = report / "inventory.txt" if report else None
    if not inventory or not inventory.is_file():
        return "not verified: the report has no inventory"
    on = _guard_on(parse_inventory(inventory.read_text(errors="replace")))
    boost, now = record["params"].get("boost"), _guard_boost(report)
    if record["params"].get("action") == "enable":
        selftest = report / "guard-selftest.txt"
        seen = selftest.read_text(errors="replace").strip() if selftest.is_file() else "none"
        if not on:
            return "NOT verified: the original runner was not kept, so the guard is not on"
        if boost and now != str(boost):
            return f"NOT verified: the guard is on, but its boost file holds {now!r}, not {boost}"
        if boost == 0 and now is not None:
            return f"NOT verified: the guard is on, but its boost file is still there ({now!r})"
        verdict = f"verified: runner guard is on (self-test: {seen})"
        if boost and "|priority 1" not in seen:
            return verdict + f", boost {boost} written, but this SYNC lacks a thread function: it will not act"
        if boost is None:  # the job left the boost as it was
            return verdict + (f", boost {now} as before" if now else "")
        return verdict + (f", boost {boost}" if boost else ", boost off")
    if on:
        return "NOT verified: the guard is still on"
    return "verified: runner guard is off" if now is None else \
        "NOT verified: the guard is off, but its boost file is still there"


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
    try:
        unchecked = store.job(args.serial, job_id).get("not_verified")
    except (OSError, ValueError):
        unchecked = None
    apps = sorted({"\\".join(e.path.split("\\")[:5]) for e in entries
                   if e.kind == "D" and e.path.lower().count("\\") >= 4})
    plugins = sorted(e.path.rsplit("\\", 1)[-1] for e in entries
                     if e.kind == "F" and e.path.lower().startswith("\\windows\\"))
    print(f"car {args.serial}, report {job_id}")
    if unchecked:  # the newest picture of the car, from a job whose own files did not check out
        print(f"  warning: job {job_id} did not pass the byte check ({unchecked}); run its undo stick")
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
    boost = _guard_boost(store.report(args.serial, job_id))
    print(f"  runner guard (fixes the freeze when leaving an app): "
          f"{('on' + (f', boost {boost}' if boost else '')) if _guard_on(entries) else 'off'}")
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


WATCH_COPIES = (("guard-live", ".log", "runner guard log"),
                ("autokit-hwlog-live", ".log", "AutoKit's own log"),
                ("autokit-hwlog-live", ".txt", "AutoKit's own log"),
                ("nav-show-live", ".txt", "SYNC's NAV_SHOW.TXT"))


def _log_text(path: Path, keep: int = 200) -> str:
    """A copied log as text (AutoKit writes UTF-16LE); a long one shows its start and its end."""
    data = path.read_bytes()
    utf16 = data[:2] == b"\xff\xfe" or (len(data) >= 4 and data[1] == 0 and data[3] == 0)
    text = data.decode("utf-16-le" if utf16 else "utf-8", errors="replace").lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").rstrip().split("\n")
    if len(lines) > keep:
        head = keep // 10
        lines = [*lines[:head], f"... {len(lines) - keep} lines left out; the whole log: {path}",
                 *lines[len(lines) - (keep - head):]]
    return "\n".join(lines)


def cmd_report(args) -> int:
    store = Store()
    job_id = args.job_id or next((r["id"] for r in reversed(store.jobs(args.serial))
                                  if store.report(args.serial, r["id"])), None)
    report = store.report(args.serial, job_id) if job_id else None
    if report is None:
        print("no imported report", file=sys.stderr)
        return 1
    print(f"report {job_id}")
    for name in ("info.txt", "busy.txt", "stale.txt", "started-before.txt", "old-report.txt",
                 "firmware-image-removed.txt", "native-hello.txt", "guard-selftest.txt", "selftest-failed.txt"):
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
    if (report / "drive.log").is_file():
        print("[drive.log: time|event|details] system facts, processor load every 10 s, screenshots, "
              "the file copy")
        print(_log_text(report / "drive.log"))
        if (report / "screens").is_dir():
            shots = sorted((report / "screens").glob("*.bmp"))
            print(f"[screens] {len(shots)} screenshots in {report / 'screens'}")
        if (report / "skins.txt").is_file():
            lines = (report / "skins.txt").read_text(errors="replace").splitlines()
            files = sum(1 for line in lines if line.startswith("F|"))
            errors = sum(1 for line in lines if line.startswith("E|"))
            total = next((line for line in lines if line.startswith("T|")), "T|not finished")
            print(f"[skins.txt] {files} screen files copied to {report / 'skins'}, {errors} failed; {total[2:]}")
        if (report / "files.txt").is_file():
            count = sum(1 for _ in (report / "files.txt").open(errors="replace"))
            print(f"[files.txt] {count} folders and files listed")
    for name, title in (("guard.log", "runner guard log when the stick ran"),
                        ("guard-live.log", "runner guard log, last copy the watcher made"),
                        ("autokit-hwlog.log", "AutoKit's own log when the stick ran"),
                        ("autokit-hwlog-live.log", "AutoKit's own log, last copy the watcher made")):
        if (report / name).is_file():
            print(f"[{name}: {title}]")
            print(_log_text(report / name))
    for name, extension, title in WATCH_COPIES:  # the watcher numbers them, one per run of the log
        for path in sorted(report.glob(f"{name}-[0-9][0-9]{extension}")):
            print(f"[{path.name}: {title}, copy {int(path.stem[-2:])} the watcher made]")
            print(_log_text(path))
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
    config.add_argument("--measure", metavar="SECONDS", type=int, nargs="?", const=LOAD_SECONDS,
                        help="also record the processor's load, clock and core voltage afterwards "
                             "(default 30 minutes), on the car; the same stick fetches the logs "
                             "when it is inserted again")
    config.set_defaults(func=cmd_job)
    job_sub.add_parser("snapshot", parents=[common],
                       help="read-only: services, startup entries and USB devices").set_defaults(func=cmd_job)
    logger = job_sub.add_parser("logger", parents=[common],
                                help="record every program and window on the screen, twice a second")
    logger.add_argument("--seconds", type=int,
                        help="default 180, four hours with --drive, 30 minutes with --load")
    kind = logger.add_mutually_exclusive_group()
    kind.add_argument("--drive", action="store_true",
                      help="also run s2amdrive.exe while you drive: screenshots, processor load, "
                           "the file list and a copy of Ford's screen files (for a redesign)")
    kind.add_argument("--load", action="store_true",
                      help="also run s2amdrive.exe for the processor's load alone, per program and "
                           "thread, writing to the car so the stick can leave (docs/PERFORMANCE.md)")
    kind.add_argument("--collect", metavar="JOB_ID",
                      help="fetch from the car what that logger --load job wrote")
    logger.add_argument("--native", action="store_true",
                        help="also run notifylog.exe, which records AutoKit's window messages")
    logger.set_defaults(func=cmd_job)
    job_sub.add_parser("native-hello", parents=[common],
                       help="prove compiled code runs on this SYNC 2").set_defaults(func=cmd_job)
    guard = job_sub.add_parser("runner-guard", parents=[common],
                               help="stop the frozen screen after leaving an app (keeps the stock "
                                    "runner for --off)")
    guard_mode = guard.add_mutually_exclusive_group()
    guard_mode.add_argument("--off", action="store_true",
                            help="put the original runner back (the boost goes with the guard)")
    guard_mode.add_argument("--boost", choices=[*map(str, BOOST_LEVELS), "off"], metavar="LEVEL",
                            help="also run the app's lowest-priority threads (AutoKit's video, 252) at "
                                 "LEVEL (250 or 251) while it is alone on the screen; 'off' turns "
                                 "only the boost off. Without it the boost stays as it is")
    guard.set_defaults(func=cmd_job)
    colours = job_sub.add_parser("theme", parents=[common],
                                 help="change SYNC's colours (Theme.XML and the four area gradients), "
                                      "backed up first; undo with --restore JOB")
    colours.add_argument("--preset", choices=theme.PRESETS, help="lincoln: the Lincoln skin's colours")
    colours.add_argument("--from", dest="source", type=Path,
                         help="a folder with your own Theme.XML and/or yellow/green/red/blue.bmp")
    colours.add_argument("--restore", metavar="JOB_ID", help="put back what that theme job replaced")
    colours.add_argument("--fetch", action="append", default=[], metavar="PATTERN",
                         help="also copy matching car files to the stick, read-only "
                              "(e.g. '\\Windows\\bt*.dll'); matched against the last drive log")
    colours.set_defaults(func=cmd_job)
    job_sub.add_parser("cleanup", parents=[common],
                       help="remove s2am's own finished job folders from the car (backups stay)"
                       ).set_defaults(func=cmd_job)
    menu = job_sub.add_parser("apps-menu", parents=[common],
                              help="a new Apps menu: SyncApps.swf plus tile pictures, backed up first; "
                                   "undo with --restore JOB")
    menu.add_argument("--swf", type=Path, help="the new SyncApps.swf (built on this Mac from the car's own)")
    menu.add_argument("--tiles", type=Path, help="a folder of tile pictures (sync-redesign tools/make_tiles.py)")
    menu.add_argument("--restore", metavar="JOB_ID", help="put back what that Apps menu job replaced")
    menu.add_argument("--fetch", action="append", default=[], metavar="PATTERN",
                      help="also copy matching car files to the stick, read-only")
    menu.set_defaults(func=cmd_job)
    screen = job_sub.add_parser("screen", parents=[common],
                                help="one of Ford's screens, rebuilt on this Mac from the car's own "
                                     "(sync-redesign), backed up first; undo with --restore JOB")
    screen.add_argument("--screen", choices=SCREENS + STARTUP_SCREENS, help="which of Ford's screens")
    screen.add_argument("--startup", action="store_true",
                        help="allow a screen SYNC loads at start-up (the frame, Home and the files they load); build its undo stick with it")
    screen.add_argument("--swf", type=Path, help="the new screen (built on this Mac from the car's own)")
    screen.add_argument("--restore", metavar="JOB_ID", help="put back what that screen job replaced")
    screen.add_argument("--fetch", action="append", default=[], metavar="PATTERN",
                        help="also copy matching car files to the stick, read-only")
    screen.set_defaults(func=cmd_job)
    faster = job_sub.add_parser("decoder", parents=[common],
                                help="replace AutoKit's three video decoder files (FFmpeg) with your own build, "
                                     "backed up first; undo with --restore JOB (not tried in the car)")
    source = faster.add_mutually_exclusive_group(required=True)
    source.add_argument("--from", dest="source", type=Path,
                        help="a folder with avcodec-56.dll, avutil-54.dll and avformat-56.dll, all three")
    source.add_argument("--restore", metavar="JOB_ID", help="put back what that decoder job replaced")
    faster.set_defaults(func=cmd_job)
    inspect = job_sub.add_parser("decoder-inspect", parents=[common],
                                help="independent native inspection of an unresolved decoder test")
    inspect.add_argument("--target", required=True, metavar="JOB_ID",
                         help="the original known decoder test job to inspect, without rerunning it")
    inspect.set_defaults(func=cmd_job)
    registry = job_sub.add_parser("registry", parents=[common],
                                  help="read-only: copy SYNC's Bluetooth, call, audio and other settings from "
                                       "the registry to the stick (link keys and PINs are not copied)")
    registry.add_argument("--root", action="append", metavar="HKLM\\PATH",
                          help=f"a registry root to copy (default: {', '.join(REGISTRY_ROOTS)})")
    registry.add_argument("--depth", type=int, default=6, help="levels below each root (0-8, default 6)")
    registry.add_argument("--fetch", action="append", default=[], metavar="PATTERN",
                          help="also copy matching car files to the stick, read-only "
                               "(e.g. '\\Windows\\boot.rgu'); matched against the last drive log")
    registry.set_defaults(func=cmd_job)
    pmic = job_sub.add_parser("pmic", parents=[common],
                              help="read-only MC13892 identification, SW1 presets and mode/SID through PMI1; "
                                   "no clock/voltage changes")
    pmic.set_defaults(func=cmd_job)
    clock = job_sub.add_parser("clock", parents=[common],
                              help="one read-only job: PMIC presets plus driver, service and system registry; "
                                   "no clock/voltage changes or restart")
    clock.add_argument("--modules", action="store_true",
                       help="targeted follow-up: PMIC mode/SID and fixed module attributes/copies, "
                            "instead of another registry capture; no overclock")
    clock.set_defaults(func=cmd_job, root=list(CLOCK_ROOTS), depth=8, fetch=[])
    bundle = job_sub.add_parser("bundle", parents=[common],
                                help="several jobs already built, in one run (theme, apps-menu, screen "
                                     "and a cleanup last); each is verified on its own after import")
    bundle.add_argument("--part", action="append", type=Path, required=True, metavar="JOB_FOLDER",
                        help="a built job's folder (build/jobs/<id>), in the order to run")
    bundle.set_defaults(func=cmd_job)
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
