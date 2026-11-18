#!/bin/sh
# Continue an existing CE build (no reconfigure). Runs INSIDE the container.
#   sh /work/tools/ce_make.sh <variant>
set -eu
B=/work/build/ce-$1
cd "$B"
if ! make -k -j"${JOBS:-10}" V=1 > make.log 2>&1; then
  echo "MAKE FAILED"
  grep -nE '(error|Error)[: ]' make.log | grep -v 'Werror' | cut -c1-300 | sort -t: -k3 -u | head -40
  grep -nE 'undefined reference' make.log | sed 's/.*undefined reference to/undef/' | sort | uniq -c | head -40
  exit 1
fi
make install > install.log 2>&1
echo "compiler warnings: $(grep -c 'warning:' make.log)"
ls -la /work/install/ce-$1/bin
