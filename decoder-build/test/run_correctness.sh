#!/bin/bash
# Correctness matrix: every DLL set x every stream x three feeding modes, under qemu-arm -cpu cortex-a8.
# Runs INSIDE ffbuild-armtest:1 with the work folder at /work and the stock AutoKit folder at /stock (ro).
#   full : 4096-byte chunks + verification drain  -> must equal the reference decode byte for byte
#   au   : one access unit per call, AutoKit loop only (no drain) -> must be an exact prefix of the reference
#   odd  : 1000-byte chunks, AutoKit loop only -> exact prefix
set -u
cd /work
SETS=${SETS:-"stock:/stock default:install/ce-default/bin small:install/ce-small/bin neon:install/ce-neon/bin"}
T=/tmp/akt; mkdir -p $T
fail=0
printf "%-8s %-28s %-5s %-9s %-7s %s\n" set stream mode result frames detail
for s in test/streams/*.h264; do
  st=$(basename "$s" .h264); ref=test/streams/$st.ref.yuv
  for e in $SETS; do
    name=${e%%:*}; dir=${e#*:}
    for mode in full au odd; do
      case $mode in full) args="4096 drain";; au) args="au";; odd) args="1000";; esac
      out=$T/$name-$st-$mode.yuv
      log=$(qemu-arm -cpu cortex-a8 test/bin/akdec "$dir" "$s" "$out" $args 2>&1); rc=$?
      res=$(echo "$log" | grep 'akdec: result' | sed 's/akdec: result //')
      frames=$(echo "$res" | sed -n 's/.*frames_total=\([0-9]*\).*/\1/p')
      if [ $rc -ne 0 ]; then verdict="CRASH/rc=$rc"; fail=1; detail=$(echo "$log" | tail -3 | tr '\n' ' ')
      else
        osz=$(stat -c %s "$out"); rsz=$(stat -c %s "$ref")
        if [ $mode = full ]; then
          if [ "$osz" = "$rsz" ] && cmp -s "$out" "$ref"; then verdict=BITEXACT; else verdict=MISMATCH; fail=1; fi
        else
          if [ "$osz" -gt 0 ] && cmp -s -n "$osz" "$out" "$ref"; then verdict=PREFIX-OK; else verdict=MISMATCH; fail=1; fi
        fi
        detail=$(echo "$res" | grep -o 'chroma_stride_mismatch=[0-9]* repacked=[0-9]*')
      fi
      printf "%-8s %-28s %-5s %-9s %-7s %s\n" "$name" "$st" "$mode" "$verdict" "$frames" "$detail"
      rm -f "$out"
    done
  done
done
echo "overall: $([ $fail = 0 ] && echo PASS || echo FAIL)"
