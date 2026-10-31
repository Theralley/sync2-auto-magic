"""Test videos for SYNC 2's Video Player: picture, smoothness, sound, left/right, A/V sync.

Usage: python3 tools/make_test_videos.py <output folder>
Copy the .mp4 files (and README.txt) to a folder on a FAT32 stick and play them in the car,
parked. Six files: a 60 s main test at 800x480, then 16 s sync tests in other formats.
Needs ffmpeg (libx264, aac), macOS `say`, and Pillow. Labels are drawn as PNGs because
this ffmpeg has no drawtext.
"""
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
RATE = 44100
SINE = 8  # ffmpeg's sine source plays at 1/8 of full scale

# Main test, 60 s. (start, end, banner, side marker, voice text, sound, channels)
MAIN = [
    (0, 8, "1  BOTH SPEAKERS: voice + 440 Hz tone", None, "Sound test. Both speakers.", "tone", "both"),
    (8, 16, "2  LEFT SPEAKER ONLY", "LEFT", "Left speaker only.", "tone", "left"),
    (16, 24, "3  RIGHT SPEAKER ONLY", "RIGHT", "Right speaker only.", "tone", "right"),
    (24, 40, "4  SYNC: each beep = white flash", None, "Sync test. Each beep should match the white flash.",
     "beeps", "both"),
    (40, 54, "5  SWEEP 50 Hz to 12 kHz", None, "Frequency sweep, low to high.", "sweep", "both"),
    (54, 60, "6  END OF TEST", None, "End of test.", None, "both"),
]
# Short files: only the sync section, to compare smoothness and sync across formats.
SHORT = [(0, 16, "SYNC + SMOOTHNESS: each beep = white flash", None, "Each beep should match the white flash.",
          "beeps", "both")]

FILES = [  # name, width, height, fps, sections, video codec arguments, what it tests
    ("01-main-800x480-h264-baseline-25fps.mp4", 800, 480, 25, MAIN,
     ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-b:v", "1500k", "-maxrate", "2000k",
      "-bufsize", "3000k"], "the main test: screen size, the simplest H.264"),
    ("02-800x480-h264-baseline-30fps.mp4", 800, 480, 30, SHORT,
     ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-b:v", "1800k", "-maxrate", "2400k",
      "-bufsize", "3600k"], "like the phone picture AutoKit decodes: 800x480, 30 fps"),
    ("03-800x480-h264-high-25fps.mp4", 800, 480, 25, SHORT,
     ["-c:v", "libx264", "-profile:v", "high", "-level", "3.1", "-b:v", "1500k", "-maxrate", "2000k",
      "-bufsize", "3000k"], "H.264 High profile, as most phones record"),
    ("04-1280x720-h264-main-25fps.mp4", 1280, 720, 25, SHORT,
     ["-c:v", "libx264", "-profile:v", "main", "-level", "3.1", "-b:v", "3000k", "-maxrate", "4000k",
      "-bufsize", "6000k"], "720p: headroom"),
    ("05-1920x1080-h264-high-25fps.mp4", 1920, 1080, 25, SHORT,
     ["-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-b:v", "6000k", "-maxrate", "8000k",
      "-bufsize", "12000k"], "1080p: probably too much; shows the limit"),
    ("06-800x480-mpeg4-25fps.mp4", 800, 480, 25, SHORT,
     ["-c:v", "mpeg4", "-tag:v", "mp4v", "-b:v", "1500k"], "MPEG-4 Part 2, the fallback if H.264 fails"),
]


def run(args):
    subprocess.run(args, check=True, capture_output=True)


def font(size):
    return ImageFont.truetype(FONT, size)


def banner(path, width, height, text):
    """Black band across the top with the section title."""
    band = max(40, height // 9)
    image = Image.new("RGBA", (width, band), (0, 0, 0, 200))
    draw = ImageDraw.Draw(image)
    size = band * 55 // 100
    while draw.textlength(text, font=font(size)) > width - 20 and size > 10:
        size -= 1
    draw.text((width // 2, band // 2), text, font=font(size), fill="white", anchor="mm")
    image.save(path)


def footer(path, width, height, text):
    band = max(28, height // 16)
    image = Image.new("RGBA", (width, band), (0, 0, 0, 170))
    ImageDraw.Draw(image).text((width // 2, band // 2), text, font=font(band * 55 // 100), fill="yellow",
                               anchor="mm")
    image.save(path)


def marker(path, width, height, text):
    """A big LEFT or RIGHT on half the screen."""
    image = Image.new("RGBA", (width // 2, height // 3), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((width // 4, height // 6), text, font=font(height // 5), fill=(255, 255, 0, 255), anchor="mm",
              stroke_width=max(2, height // 120), stroke_fill="black")
    image.save(path)


def flash(path, width, height):
    side = height // 4
    Image.new("RGBA", (side, side), (255, 255, 255, 255)).save(path)


def voice(path, text):
    run(["say", "-r", "175", "-o", str(path), text])
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], check=True, capture_output=True, text=True).stdout
    return float(out)


def pan(channels):
    return {"both": "pan=stereo|c0=c0|c1=c0", "left": "pan=stereo|c0=c0|c1=0*c0",
            "right": "pan=stereo|c0=0*c0|c1=c0"}[channels]


def render(out_dir, work, spec):
    name, width, height, fps, sections, vcodec, _ = spec
    duration = sections[-1][1]
    stem = Path(name).stem
    inputs = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={duration}"]
    video, audio, chains = "[0:v]", [], []
    count = 1

    def add_input(args):
        nonlocal count
        inputs.extend(args)
        count += 1
        return count - 1

    info = (f"{width}x{height}  {fps} fps  "
            + ("H.264 " + vcodec[vcodec.index("-profile:v") + 1] if "libx264" in vcodec else "MPEG-4")
            + "  AAC stereo 128k")
    footer(work / f"{stem}-footer.png", width, height, info)
    index = add_input(["-i", str(work / f"{stem}-footer.png")])
    chains.append(f"{video}[{index}:v]overlay=0:H-h[v{index}]")
    video = f"[v{index}]"
    flash(work / f"{stem}-flash.png", width, height)
    flash_input = add_input(["-i", str(work / f"{stem}-flash.png")])
    for number, (start, end, title, side, said, sound, channels) in enumerate(sections):
        png = work / f"{stem}-banner{number}.png"
        banner(png, width, height, title)
        index = add_input(["-i", str(png)])
        # above the footer, so testsrc2's clock in the top left corner stays visible
        chains.append(f"{video}[{index}:v]overlay=0:H-h-{max(28, height // 16)}:"
                      f"enable='between(t,{start},{end - 0.001})'[v{index}]")
        video = f"[v{index}]"
        if side:
            png = work / f"{stem}-side{number}.png"
            marker(png, width, height, side)
            index = add_input(["-i", str(png)])
            x = "0" if side == "LEFT" else "W/2"
            chains.append(f"{video}[{index}:v]overlay={x}:(H-h)/2:enable='between(t,{start},{end - 0.001})'"
                          f"[v{index}]")
            video = f"[v{index}]"
        wav = work / f"{stem}-voice{number}.aiff"
        spoken = voice(wav, said)
        index = add_input(["-i", str(wav)])
        audio.append(f"[{index}:a]aresample={RATE},aformat=channel_layouts=mono,{pan(channels)},"
                     f"adelay=delays={int((start + 0.4) * 1000)}:all=1")
        begin = math.ceil(start + 0.4 + spoken + 0.5)  # sound starts on a whole second after the voice
        if sound == "tone" and begin < end:
            audio.append(f"sine=frequency=440:sample_rate={RATE}:duration={end - begin},volume={0.25 * SINE},{pan(channels)},"
                         f"adelay=delays={begin * 1000}:all=1")
        elif sound == "beeps" and begin < end:
            audio.append(f"sine=frequency=1000:sample_rate={RATE}:samples_per_frame=441:duration={end - begin},"
                         f"volume='if(lt(mod(t,1),0.1),{0.4 * SINE},0)':eval=frame,{pan(channels)},"
                         f"adelay=delays={begin * 1000}:all=1")
            chains.append(f"{video}[{flash_input}:v]overlay=W-w-{width // 20}:(H-h)/2:"
                          f"enable='between(t,{begin},{end - 0.001})*lt(mod(t,1),0.1)'[vf{number}]")
            video = f"[vf{number}]"
        elif sound == "sweep" and begin < end:
            span, low, high = end - begin - 1, 50, 12000
            ratio = high / low
            audio.append(f"aevalsrc=exprs='0.25*sin(2*PI*{low}*{span}/log({ratio})*(pow({ratio},t/{span})-1))'"
                         f":s={RATE}:d={span}:c=mono,{pan(channels)},adelay=delays={begin * 1000}:all=1")
    labels = []
    for number, chain in enumerate(audio):
        chains.append(f"{chain}[a{number}]")
        labels.append(f"[a{number}]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                  f"apad,atrim=0:{duration}[aout]")
    graph = ";".join(chains)
    target = out_dir / name
    run(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", graph, "-map", video, "-map", "[aout]",
         "-t", str(duration), *vcodec, "-pix_fmt", "yuv420p", "-g", str(fps * 2), "-c:a", "aac", "-b:a", "128k",
         "-ar", str(RATE), "-ac", "2", "-movflags", "+faststart", str(target)])
    return target


def main():
    out_dir = Path(sys.argv[1])
    work = out_dir.parent / "work"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    for spec in FILES:
        target = render(out_dir, work, spec)
        print(f"{target.name}: {target.stat().st_size // 1024} KB - {spec[6]}")
    shutil.copyfile(Path(__file__).with_name("test-videos-README.txt"), out_dir / "README.txt")


if __name__ == "__main__":
    main()
