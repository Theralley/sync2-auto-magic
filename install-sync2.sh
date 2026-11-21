#!/bin/sh
# Linux: run this file to start the guided installer (./install-sync2.sh, or double-click and
# choose "Run in Terminal"). macOS: double-click Install-SYNC2.command instead.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Install it with your package manager (for example: sudo apt install python3)."
  exit 1
fi
for tool in docker lsblk findmnt udisksctl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing: $tool. Install it first (Docker from https://docs.docker.com/engine/install/;"
    echo "lsblk and findmnt are in util-linux, udisksctl is in udisks2)."
    exit 1
  fi
done
exec python3 -m s2am wizard
