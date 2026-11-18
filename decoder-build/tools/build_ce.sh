#!/bin/sh
# Build FFmpeg 2.6.9 for Windows CE ARM with CeGCC, inside the pinned ENLYZE image.
# Runs INSIDE the container; the work folder is mounted at /work.
#   sh /work/tools/build_ce.sh <variant>
# Variants:
#   default  cortex-a8 tuning, ARMv5TE/ARMv6/ARMv6T2 asm, NO NEON, NO VFP, soft-float
#   neon     EXPERIMENTAL: as default plus NEON assembly (C code still soft-float)
#   small    reference: same switches as the stock DLLs (--enable-small, ARMv4T, no asm ext)
set -eu
V=$1
SRC=${SRC:-/work/src/ffmpeg-2.6.9}   # patched FFmpeg 2.6.9 tree (see patches/)
B=/work/build/ce-$V${TAG:-}
P=/work/install/ce-$V${TAG:-}

COMMON="--target-os=mingw32ce --arch=arm --enable-cross-compile --cross-prefix=arm-mingw32ce-
 --prefix=$P --disable-static --enable-shared
 --disable-debug --disable-doc --disable-programs
 --disable-avdevice --disable-swresample --disable-swscale --disable-postproc --disable-avfilter
 --disable-network --disable-everything
 --enable-decoder=h264 --enable-parser=h264
 --enable-memalign-hack
 --disable-pthreads --disable-w32threads --disable-os2threads
 --disable-zlib --disable-bzlib --disable-lzma --disable-iconv --disable-sdl --disable-xlib
 --disable-dxva2 --disable-vaapi --disable-vda --disable-vdpau
 --disable-pic"
# -mno-unaligned-access: Windows CE ARM faults on unaligned loads (Datatype Misalignment).
# -mword-relocations: PE/COFF ARM cannot represent MOVW/MOVT relocations (GCC uses them
#   for symbol addresses from ARMv6T2 on); force literal-pool loads instead.
# -I/work/ce-compat: errno.h replacement (the toolchain's one is broken for __COREDLL__).
CE_CFLAGS="-I/work/ce-compat -DWINCE -D_WIN32_WCE=0x600 -DUNDER_CE -mfloat-abi=soft -mno-unaligned-access -mword-relocations"
CE_LDFLAGS="-static -Wl,--major-subsystem-version,6 -Wl,--minor-subsystem-version,0"

case "$V" in
  default)
    EXTRA="--cpu=cortex-a8 --enable-armv5te --enable-armv6 --enable-armv6t2
           --disable-neon --disable-vfp --disable-fast-unaligned --disable-setend" ;;
  neon)
    EXTRA="--cpu=cortex-a8 --enable-armv5te --enable-armv6 --enable-armv6t2
           --enable-neon --disable-vfp --disable-fast-unaligned --disable-setend"
    # C code stays soft-float (no VFP/NEON from the compiler); only the assembler is
    # told NEON exists, so FFmpeg's hand-written NEON .S files assemble.
    CE_CFLAGS="$CE_CFLAGS -Wa,-mfpu=neon" ;;
  small)
    EXTRA="--enable-small --disable-armv5te --disable-armv6 --disable-armv6t2
           --disable-neon --disable-vfp --disable-fast-unaligned --disable-setend" ;;
  *) echo "unknown variant $V"; exit 2 ;;
esac

rm -rf "$B" "$P"
mkdir -p "$B"
cd "$B"
echo "configure $COMMON $EXTRA --extra-cflags=\"$CE_CFLAGS\" --extra-ldflags=\"$CE_LDFLAGS\"" > configure-cmdline.txt
# shellcheck disable=SC2086
if ! "$SRC/configure" $COMMON $EXTRA --extra-cflags="$CE_CFLAGS" --extra-ldflags="$CE_LDFLAGS" > configure.out 2>&1; then
  echo "CONFIGURE FAILED"; tail -40 configure.out; tail -60 config.log; exit 1
fi
cat configure.out | sed -n '1,60p'
if ! make -j"${JOBS:-8}" V=1 > make.log 2>&1; then
  echo "MAKE FAILED"; grep -nE 'error|Error' make.log | head -40; tail -30 make.log; exit 1
fi
# Headers (for the ABI check) via make; the DLLs are copied and stripped explicitly,
# exactly as FFmpeg's install rule does (install + $(STRIP)).
make install-headers > install.log 2>&1 || make install-headers > install.log 2>&1 \
  || { echo "WARNING: make install-headers failed, see install.log"; }
mkdir -p "$P/bin" "$P/unstripped"
for d in libavutil/avutil-54.dll libavcodec/avcodec-56.dll libavformat/avformat-56.dll; do
  cp "$d" "$P/unstripped/"
  cp "$d" "$P/bin/"
  arm-mingw32ce-strip "$P/bin/$(basename "$d")"
done
echo "compiler warnings: $(grep -c 'warning:' make.log || true)"
grep 'warning:' make.log | sed 's/.*warning: //' | sort | uniq -c | sort -rn | head -25
ls -la "$P/bin" "$P/unstripped"
