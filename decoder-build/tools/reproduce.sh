#!/bin/bash
# Rebuild the AutoKit FFmpeg DLLs from nothing but public inputs, then run every check.
#   tools/reproduce.sh            (run from the work folder; needs Docker and network for step 1-2)
#
# Inputs (all pinned):
#   FFmpeg 2.6.9 source  https://ffmpeg.org/releases/ffmpeg-2.6.9.tar.xz
#                        sha256 a8fd3d0d47d4951818d56f0ec81e7e3144c4bdfc008cfe43c0a6ca842f336a51
#                        (signature ffmpeg-2.6.9.tar.xz.asc, FFmpeg release key
#                         FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8)
#   patch                patches/ffmpeg-2.6.9-wince-autokit.patch (8 files, apply with -p1)
#   errno shim           ce-compat/errno.h (passed with -I, not part of the FFmpeg tree)
#   toolchain image      ghcr.io/enlyze/windows-ce-build-environment-arm@sha256:22ea23d6...dfe27c
#                        (arm-mingw32ce-gcc 9.3.0, binutils 2.34)
#   test image           test/docker/Dockerfile (debian bookworm-slim pinned by digest)
set -eu
W=$(cd "$(dirname "$0")/.." && pwd)
cd "$W"
IMG=ghcr.io/enlyze/windows-ce-build-environment-arm@sha256:22ea23d697accaab2b98fb12d81ccc1faade90f9fe490f554ae7c5c194dfe27c

# 1. source
mkdir -p dl src
[ -f dl/ffmpeg-2.6.9.tar.xz ] || curl -fL -o dl/ffmpeg-2.6.9.tar.xz https://ffmpeg.org/releases/ffmpeg-2.6.9.tar.xz
echo "a8fd3d0d47d4951818d56f0ec81e7e3144c4bdfc008cfe43c0a6ca842f336a51  dl/ffmpeg-2.6.9.tar.xz" | shasum -a 256 -c -
rm -rf src/ffmpeg-2.6.9
tar -xJf dl/ffmpeg-2.6.9.tar.xz -C src
(cd src/ffmpeg-2.6.9 && patch -p1 < "$W/patches/ffmpeg-2.6.9-wince-autokit.patch")

# 2. toolchain
docker image inspect "$IMG" >/dev/null 2>&1 || docker pull --platform linux/amd64 "$IMG"

# 3. build (default = the deliverable; small = stock-equivalent switches; neon = experimental)
for V in default small neon; do
  docker run --rm --platform linux/amd64 --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -e JOBS=4 \
    -v "$W:/work" -w /work "$IMG" sh /work/tools/build_ce.sh "$V" > "logs/build-ce-$V.log" 2>&1
  echo "build $V: OK ($(ls install/ce-$V/bin))"
done

# 3b. neon-safe = the neon variant with the NEON routines that fault on the car left to C
#     (patches/ffmpeg-2.6.9-neon-aligned-only.patch, see README.md). Lands in install/ce-neon-safe.
rm -rf src-safe && mkdir src-safe && cp -R src/ffmpeg-2.6.9 src-safe/
(cd src-safe/ffmpeg-2.6.9/libavcodec/arm && patch -p4 < "$W/patches/ffmpeg-2.6.9-neon-aligned-only.patch")
docker run --rm --platform linux/amd64 --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -e JOBS=4 \
  -e SRC=/work/src-safe/ffmpeg-2.6.9 -e TAG=-safe \
  -v "$W:/work" -w /work "$IMG" sh /work/tools/build_ce.sh neon > logs/build-ce-neon-safe.log 2>&1
echo "build neon-safe: OK ($(ls install/ce-neon-safe/bin))"

# 4. static checks (PE structure, imports vs car-proven binaries, exports, ABI, instruction set)
tools/run_checks.sh

# 5. emulator tests (need the stock DLLs read-only for the comparison, and a host ffmpeg with
#    libx264 to make the test streams: see test/make_streams.sh)
docker build --platform linux/arm64 -t ffbuild-armtest:1 test/docker
test/make_streams.sh
docker run --rm --platform linux/arm64 --network none -u "$(id -u):$(id -g)" -v "$W:/work" -w /work ffbuild-armtest:1 sh -c '
  gcc -shared -fPIC -O2 -Wall -I dl/qemu-7.2 $(pkg-config --cflags glib-2.0) -o test/bin/akprof.so test/qplugin/akprof.c $(pkg-config --libs glib-2.0)
  arm-linux-gnueabi-gcc -O2 -Wall -Wno-unused-parameter -static -marm -march=armv7-a -mfloat-abi=soft -o test/bin/akdec test/peload/akdec.c -lm'
STOCK=${STOCK:?set STOCK to the folder with the AutoKit app as shipped (its three original DLLs)}
for t in "run_correctness.sh" "run_perf.sh perf" "run_perf.sh align"; do
  docker run --rm --platform linux/arm64 --network none -u "$(id -u):$(id -g)" -v "$W:/work" -v "$STOCK:/stock:ro" \
    -w /work ffbuild-armtest:1 bash /work/test/$t
done
