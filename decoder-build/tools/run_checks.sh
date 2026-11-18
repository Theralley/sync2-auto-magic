#!/bin/bash
# Static checks on the built DLLs. Run on the host from anywhere; writes analysis/*.txt.
#   tools/run_checks.sh
# Needs: Docker (ENLYZE CeGCC image), venv/ with pefile+capstone, the stock AutoKit folder (read only)
# and the car-proven s2am native exes (read only, for the "import seen on the car" check).
set -u
W=$(cd "$(dirname "$0")/.." && pwd)
cd "$W"
IMG=ghcr.io/enlyze/windows-ce-build-environment-arm@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c
STOCK=${STOCK:?set STOCK to the folder with the AutoKit app as shipped (its three original DLLs)}
NAT=${NAT:-$W/../build/native}  # the car-proven programs of this repo (s2am native build)
PY="$W/venv/bin/python -I"

# 1. symbol maps of the unstripped DLLs + ABI static asserts against the installed headers
docker run --rm --platform linux/amd64 --network none -u "$(id -u):$(id -g)" -v "$W:/work" -w /work $IMG sh -c '
for V in default small neon; do
  for d in install/ce-$V/unstripped/*.dll; do arm-mingw32ce-nm -n "$d" > "${d%.dll}.nm"; done
  arm-mingw32ce-gcc -c -o /tmp/abi_$V.o -I/work/ce-compat -I install/ce-$V/include -mfloat-abi=soft -w \
    test/abi/abi_check.c && echo "ABI $V: PASS" || echo "ABI $V: FAIL"
done' > analysis/abi_check.txt 2>&1
cat analysis/abi_check.txt

# 2. PE structure, imports vs car-proven binaries, AutoKit's 16 exports
for V in default small neon; do
  echo "######## $V"; $PY tools/check_dlls.py install/ce-$V/bin "$STOCK" "$NAT"; echo "exit=$?"
done > analysis/check_dlls.txt 2>&1
grep -E '########|exit=' analysis/check_dlls.txt | paste -sd' ' -

# 3. instruction-set scan (VFP/NEON/coprocessor/barriers/setend inventory)
for V in default small neon; do
  $PY tools/isa_scan.py --nm install/ce-$V/unstripped/avcodec-56.nm --nm install/ce-$V/unstripped/avformat-56.nm \
      --nm install/ce-$V/unstripped/avutil-54.nm --show 4 \
      install/ce-$V/bin/avcodec-56.dll install/ce-$V/bin/avutil-54.dll install/ce-$V/bin/avformat-56.dll \
      > analysis/isa-$V.txt 2>&1
done
$PY tools/isa_scan.py --show 4 "$STOCK/avcodec-56.dll" "$STOCK/avutil-54.dll" "$STOCK/avformat-56.dll" > analysis/isa-stock.txt 2>&1
for V in default small neon stock; do
  echo "## isa $V: $(grep -E '^==|  cp1[01] |NEON-|op:ldrex|op:strex|op:dmb|op:setend|op:swp ' analysis/isa-$V.txt \
     | sed -e 's#.*/##' -e 's/   e\.g\..*//' | tr -s ' ' | paste -sd' ' -)"
done
