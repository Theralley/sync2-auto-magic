#!/bin/bash
# Emulator performance + alignment run. INSIDE ffbuild-armtest:1, work folder at /work, stock at /stock (ro).
#   perf : guest instructions executed inside the three DLL images (qemu plugin, inline counters),
#          AutoKit loop with 4096-byte chunks, no output file; plus wall time without plugin, min of 3.
#   align: same run with every DLL load/store checked for natural alignment (SCTLR.A=1 semantics).
set -u
cd /work
SETS=${SETS:-"stock:/stock default:install/ce-default/bin small:install/ce-small/bin neon:install/ce-neon/bin"}
P=test/bin/akprof.so
ranges() { # plugin args for the image ranges the harness reports for a DLL set
  qemu-arm -cpu cortex-a8 test/bin/akdec "$1" /nonexistent - 2>&1 | sed -n 's/^akdec: image \([a-z]*\)-[0-9]*\.dll \(0x[0-9a-f]*\)-\(0x[0-9a-f]*\)$/range=\2:\3:\1/p' | paste -sd, -
}
mode=${1:-perf}
printf "%-8s %-28s %8s %14s %14s %12s %12s %10s %s\n" set stream frames dll_insns total_insns avcodec avutil wall_min_s note
for s in test/streams/*.h264; do
  st=$(basename "$s" .h264)
  for e in $SETS; do
    name=${e%%:*}; dir=${e#*:}
    R=$(ranges "$dir")
    if [ "$mode" = align ]; then
      log=$(qemu-arm -cpu cortex-a8 -d plugin -plugin "$P,$R,align=1" test/bin/akdec "$dir" "$s" - 4096 drain 2>&1)
      echo "== $name $st: $(echo "$log" | grep -E 'akdec: result' | grep -o 'frames_total=[0-9]*') $(echo "$log" | grep 'unaligned_accesses')"
      echo "$log" | grep 'akprof: unaligned pc' | head -20
      continue
    fi
    log=$(qemu-arm -cpu cortex-a8 -d plugin -plugin "$P,$R" test/bin/akdec "$dir" "$s" - 4096 2>&1)
    frames=$(echo "$log" | sed -n 's/.*frames_total=\([0-9]*\).*/\1/p')
    tot=$(echo "$log" | sed -n 's/^akprof: total_insns \([0-9]*\)/\1/p')
    ac=$(echo "$log" | sed -n 's/^akprof: range avcodec .* insns \([0-9]*\)/\1/p')
    au=$(echo "$log" | sed -n 's/^akprof: range avutil .* insns \([0-9]*\)/\1/p')
    af=$(echo "$log" | sed -n 's/^akprof: range avformat .* insns \([0-9]*\)/\1/p')
    best=
    for i in 1 2 3; do
      w=$(qemu-arm -cpu cortex-a8 test/bin/akdec "$dir" "$s" - 4096 2>&1 | sed -n 's/.*decode_seconds=\([0-9.]*\).*/\1/p')
      best=$(echo "$best $w" | tr ' ' '\n' | grep . | sort -g | head -1)
    done
    printf "%-8s %-28s %8s %14s %14s %12s %12s %10s %s\n" "$name" "$st" "$frames" $((ac + au + af)) "$tot" "$ac" "$au" "$best" "avformat=$af"
  done
done
