#!/bin/bash
# Make the H.264 test streams and their reference decodes (host ffmpeg with libx264;
# used here: Homebrew ffmpeg 9.0.1). All streams carry access unit delimiters (aud=1)
# so akdec's "au" mode can feed one access unit per call.
set -eu
cd "$(dirname "$0")/streams" 2>/dev/null || { mkdir -p "$(dirname "$0")/streams"; cd "$(dirname "$0")/streams"; }
FF=${FF:-/opt/homebrew/bin/ffmpeg}
q="-hide_banner -loglevel error -y"
$FF $q -f lavfi -i "testsrc2=size=800x480:rate=15" -frames:v 150 -pix_fmt yuv420p -c:v libx264 -profile:v baseline -preset medium -b:v 2M -g 60 -x264-params aud=1 -f h264 s1_baseline_800x480.h264
$FF $q -f lavfi -i "mandelbrot=size=800x480:rate=15" -frames:v 150 -pix_fmt yuv420p -c:v libx264 -profile:v main -preset medium -bf 0 -b:v 3M -g 60 -x264-params aud=1 -f h264 s2_main_cabac_800x480.h264
$FF $q -f lavfi -i "testsrc2=size=800x480:rate=15" -vf "noise=alls=12:allf=t" -frames:v 150 -pix_fmt yuv420p -c:v libx264 -profile:v high -preset medium -bf 2 -b:v 4M -g 60 -x264-params aud=1:weightp=2 -f h264 s3_high_bframes_800x480.h264
$FF $q -f lavfi -i "mandelbrot=size=640x384:rate=15" -frames:v 90 -pix_fmt yuv420p -c:v libx264 -profile:v high -preset medium -bf 0 -b:v 2M -g 30 -x264-params aud=1 -f h264 s4_high_640x384.h264
$FF $q -f lavfi -i "testsrc2=size=850x480:rate=15" -frames:v 60 -pix_fmt yuv420p -c:v libx264 -profile:v main -preset medium -bf 0 -b:v 2M -g 30 -x264-params aud=1 -f h264 s5_main_850x480_crop.h264
for s in s1_baseline_800x480 s2_main_cabac_800x480 s3_high_bframes_800x480 s4_high_640x384 s5_main_850x480_crop; do
  $FF $q -i $s.h264 -f rawvideo -pix_fmt yuv420p $s.ref.yuv
done
