#!/bin/bash
# Double-click this file in Finder to start the guided installer in Terminal.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close."
  exit 1
fi
python3 -m s2am wizard
read -r -p "Press Enter to close this window."
