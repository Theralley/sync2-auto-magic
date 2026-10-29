"""Run SyncExtPack's upstream tools in the offline linux/amd64 builder image."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE = "sync2-auto-magic-builder"
DOCKER_DESKTOP_BIN = Path("/Applications/Docker.app/Contents/Resources/bin")


class ContainerError(Exception):
    pass


def docker() -> list[str]:
    binary = shutil.which("docker") or str(DOCKER_DESKTOP_BIN / "docker")
    if not Path(binary).exists():
        raise ContainerError("Docker CLI not found; start Docker Desktop")
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


def ensure_image() -> None:
    subprocess.run(docker() + ["build", "--platform", "linux/amd64", "-q", "-t", IMAGE,
                               str(REPO / "docker")], check=True, env=docker_env(),
                   stdout=subprocess.DEVNULL)


def run(workdir: Path, *command: str, quiet: bool = False) -> None:
    """Run ``command`` in the image with ``workdir`` mounted at /work, without network.

    ``quiet`` keeps the tool's output unless it fails (crypto_pack prints debug noise).
    """
    workdir = workdir.resolve()  # a relative name would mount a Docker volume instead
    result = subprocess.run(docker() + ["run", "--rm", "--platform", "linux/amd64",
                                        "--network", "none", "-u", f"{os.getuid()}:{os.getgid()}",
                                        "-e", "HOME=/tmp", "-v", f"{workdir}:/work", "-w", "/work",
                                        IMAGE, *command], env=docker_env(),
                            capture_output=quiet, text=quiet)
    if result.returncode:
        if quiet:
            raise ContainerError(f"{command[0]} failed ({result.returncode}): "
                                 f"{(result.stderr or result.stdout)[-500:]}")
        raise subprocess.CalledProcessError(result.returncode, command)
