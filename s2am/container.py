"""Run SyncExtPack's upstream tools in the offline linux/amd64 builder image."""
from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
IMAGE = "sync2-auto-magic-builder"
DOCKER_DESKTOP_BIN = Path("/Applications/Docker.app/Contents/Resources/bin")
DOCKER_WINDOWS_BIN = Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "Docker", "Docker", "resources", "bin")


def _desktop_bin() -> Path:
    """Where Docker Desktop keeps its programs, for when they are not on PATH."""
    return DOCKER_WINDOWS_BIN if os.name == "nt" else DOCKER_DESKTOP_BIN


class ContainerError(Exception):
    pass


def docker() -> list[str]:
    binary = shutil.which("docker") or str(_desktop_bin() / ("docker.exe" if os.name == "nt" else "docker"))
    if not Path(binary).exists():
        raise ContainerError("Docker was not found; install it (Docker Desktop on macOS and Windows, Docker "
                             "Engine on Linux) and start it")
    return [binary]


def docker_env() -> dict[str, str]:
    env = dict(os.environ)
    # The CLI's credential helper (docker-credential-desktop) lives here.
    if _desktop_bin().is_dir():
        env["PATH"] = f"{_desktop_bin()}{os.pathsep}{env.get('PATH', '')}"
    socket = Path.home() / ".docker" / "run" / "docker.sock"
    if "DOCKER_HOST" not in env and socket.exists():
        env["DOCKER_HOST"] = f"unix://{socket}"
    return env


@functools.lru_cache(maxsize=1)
def _docker_info_security() -> str:
    try:
        result = subprocess.run(docker() + ["info", "--format", "{{json .SecurityOptions}}"],
                                env=docker_env(), capture_output=True, text=True)
    except (ContainerError, OSError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def user_args(system: str | None = None, security: Callable[[], str] = _docker_info_security) -> list[str]:
    """Who the tools run as inside the container, so the files they write belong to the user.

    Docker Desktop and an ordinary Docker Engine: the user's own uid:gid. Rootless Docker maps the
    container's root to the user and every other uid to someone else, so there it is 0:0. Windows
    has no uid (issue #6) and Docker Desktop maps file owners itself."""
    if not hasattr(os, "getuid"):
        return []
    if (system or platform.system()) == "Linux" and "rootless" in security():
        return ["-u", "0:0"]
    return ["-u", f"{os.getuid()}:{os.getgid()}"]


def emulation_problem(system: str | None = None, machine: str | None = None,
                      binfmt: Path = Path("/proc/sys/fs/binfmt_misc")) -> str | None:
    """The build tools are x86-64 programs. Docker Desktop on a Mac runs them on any processor; a
    Linux computer with another processor needs x86-64 emulation registered with the kernel."""
    machine = (machine or platform.machine()).lower()
    if (system or platform.system()) != "Linux" or machine in ("x86_64", "amd64"):
        return None

    def enabled(path: Path) -> bool:  # binfmt_misc files start with "enabled" or "disabled"
        try:
            return path.read_text().split("\n", 1)[0].strip() == "enabled"
        except (OSError, UnicodeDecodeError):
            return False

    try:
        if enabled(binfmt / "status") and any(
                ("x86_64" in entry.name or "x86-64" in entry.name) and enabled(entry) for entry in binfmt.iterdir()):
            return None
    except OSError:
        pass
    return (f"this computer has a {machine} processor and the build tools are x86-64 programs. Docker "
            "can run them only with x86-64 emulation: install it (Debian and Ubuntu: sudo apt install "
            "qemu-user-static binfmt-support) and start the installer again.")


def ensure_image() -> None:
    subprocess.run(docker() + ["build", "--platform", "linux/amd64", "-q", "-t", IMAGE,
                               str(REPO / "docker")], check=True, env=docker_env(),
                   stdout=subprocess.DEVNULL)


def run(workdir: Path, *command: str, quiet: bool = False, image: str = IMAGE) -> None:
    """Run ``command`` in ``image`` with ``workdir`` mounted at /work, without network.

    ``quiet`` keeps the tool's output unless it fails (crypto_pack prints debug noise).
    """
    workdir = workdir.resolve()  # a relative name would mount a Docker volume instead
    result = subprocess.run(docker() + ["run", "--rm", "--platform", "linux/amd64",
                                        "--network", "none", *user_args(),
                                        "-e", "HOME=/tmp", "-v", f"{workdir}:/work", "-w", "/work",
                                        image, *command], env=docker_env(),
                            capture_output=quiet, text=quiet)
    if result.returncode:
        if quiet:
            raise ContainerError(f"{command[0]} failed ({result.returncode}): "
                                 f"{(result.stderr or result.stdout)[-500:]}")
        raise subprocess.CalledProcessError(result.returncode, command)
