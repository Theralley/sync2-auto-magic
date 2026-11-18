#!/bin/bash
# Every address in the DLLs that makes an unaligned access, over all test streams, for one set.
# INSIDE ffbuild-armtest:1, work folder at /work. Result: analysis/safe-unaligned-offsets.txt
# (classify with capstone: only vld1.8/vst1.8 and vpush/vpop may remain).
set -u
cd /work
dir=install/ce-neon-safe/bin
P=test/bin/akprof.so
R=$(qemu-arm -cpu cortex-a8 test/bin/akdec "$dir" /nonexistent - 2>&1 | sed -n 's/^akdec: image \([a-z]*\)-[0-9]*\.dll \(0x[0-9a-f]*\)-\(0x[0-9a-f]*\)$/range=\2:\3:\1/p' | paste -sd, -)
for s in test/streams/*.h264; do
  qemu-arm -cpu cortex-a8 -d plugin -plugin "$P,$R,align=1" test/bin/akdec "$dir" "$s" - 4096 drain 2>&1 | grep 'akprof: unaligned pc'
done | sed -n 's/.*(\([a-z]*\)+0x\([0-9a-f]*\)).*/\1 \2/p' | sort -u > /work/analysis/safe-unaligned-offsets.txt
wc -l /work/analysis/safe-unaligned-offsets.txt
