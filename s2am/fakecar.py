"""A stand-in for SYNC 2 in tests: UpdateService's behaviour plus the inventory job's effect.

It cannot read install.bin (that is crypto_pack's business), so the test hands
it the staging folder the install.bin was built from. Everything else follows
what UpdateService does on the car: case-insensitive paths, files copied over
existing ones, POST_APP run after copying, install_log.txt on the stick, and
install.bin renamed to installed.bin unless installed.bin is already there.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .job import (AUTOKIT_CE, AUTOKIT_MODULES, INVENTORY_ROOT, MENU_XML, PLUGINS_MASK,
                  REPORTS_DIR, Job, ce_path)


class FakeCar:
    def __init__(self, root: Path, serial: str):
        self.root = root
        self.serial = serial
        self.runs = 0
        self.autokit_running = False
        root.mkdir(parents=True, exist_ok=True)

    # Paths -----------------------------------------------------------------
    def _resolve(self, ce: str, base: Path | None = None) -> Path:
        """Map a CE path onto the fake root, matching existing names case-insensitively."""
        current = base or self.root
        for part in [p for p in ce.replace("\\", "/").split("/") if p]:
            match = next((c for c in current.iterdir() if c.name.lower() == part.lower()),
                         None) if current.is_dir() else None
            current = match or current / part
        return current

    def _ce(self, path: Path) -> str:
        return "\\" + str(path.relative_to(self.root)).replace("/", "\\")

    def put(self, ce: str, data: bytes) -> None:
        path = self._resolve(ce)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, ce: str) -> bool:
        return self._resolve(ce).exists()

    # UpdateService ----------------------------------------------------------
    def insert(self, stick: Path, staged: Path, job: Job) -> None:
        updater = stick / "SyncExtPack"
        install = updater / "install.bin"
        if not install.exists():
            return
        if job.serial != self.serial:
            (updater / "install_log.txt").write_text("Error: wrong APIM serial\n")
            return
        self.runs += 1
        payload = staged / "payload"
        for source in sorted(payload.rglob("*")):
            target = self._resolve(str(source.relative_to(payload)))
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)  # CREATE_ALWAYS
        self._run_inventory(stick, job)
        (updater / "install_log.txt").write_text("Install successfully completed!\n")
        if not (updater / "installed.bin").exists():  # otherwise the rename fails silently
            install.rename(updater / "installed.bin")

    # The job scripts' effect --------------------------------------------------
    def _run_inventory(self, stick: Path, job: Job) -> None:
        out = stick / job.report_dir.replace(REPORTS_DIR.split("/s2am")[0] + "/", "")
        out.mkdir(parents=True, exist_ok=True)
        if self.exists(job.done_marker):
            (out / "replayed.txt").write_text(job.id)
            return
        variant = {"akstock": "orig", "akpatch": "patched"}.get(job.kind)
        if variant:
            if self.autokit_running:
                (out / "busy.txt").write_text("AutoKit is running")
                return
            for module in AUTOKIT_MODULES:
                source = self._resolve(f"{AUTOKIT_CE}\\{module}.{variant}")
                if source.exists():
                    shutil.copyfile(source, self._resolve(f"{AUTOKIT_CE}\\{module}"))
        lines = []
        apps = self._resolve(INVENTORY_ROOT)

        def walk(folder: Path, depth: int) -> None:
            """Same reach as the script: files at every level, folders down to depth 3."""
            for entry in sorted(folder.iterdir()):
                if entry.is_file():
                    lines.append(f"F|{self._ce(entry)}|{entry.stat().st_size}")
            if depth < 3:
                for entry in sorted(folder.iterdir()):
                    if entry.is_dir():
                        lines.append(f"D|{self._ce(entry)}")
                        walk(entry, depth + 1)

        if apps.is_dir():
            for category in sorted(p for p in apps.iterdir() if p.is_dir()):
                lines.append(f"D|{self._ce(category)}")
                walk(category, 1)
        plugins = self._resolve(ce_path(PLUGINS_MASK).rsplit("\\", 1)[0])
        if plugins.is_dir():
            for dll in sorted(plugins.iterdir()):
                if dll.name.lower().endswith("plugin.dll"):
                    lines.append(f"F|{self._ce(dll)}|{dll.stat().st_size}")
        (out / "inventory.txt").write_text("".join(line + "\r\n" for line in lines))
        menu = self._resolve(MENU_XML)
        if menu.exists():
            shutil.copyfile(menu, out / "SyncApps.xml")
        self.put(job.done_marker, job.id.encode())
        (out / "done.txt").write_text(f"{job.id} applied")
        (out / "info.txt").write_text(f"job={job.id}\r\ntime=2026-10-30 12:00:00\r\n"
                                      f"mortscript=4.2\r\nfree=123456\r\n")
