s2am test videos for SYNC 2's Video Player (made 2026-10-30)

Play them only when parked.

01-main-800x480-h264-baseline-25fps.mp4  (60 s, the main test)
  1  0-8 s    voice + tone from BOTH speakers
  2  8-16 s   LEFT speaker only
  3  16-24 s  RIGHT speaker only
  4  24-40 s  a beep every second; the white square should flash at the same moment
  5  40-54 s  sweep from 50 Hz (deep) to 12 kHz (high)
  6  54-60 s  end
02-800x480-h264-baseline-30fps.mp4   like the phone picture AutoKit gets: 800x480, 30 fps
03-800x480-h264-high-25fps.mp4       H.264 High profile, as phones record
04-1280x720-h264-main-25fps.mp4      720p
05-1920x1080-h264-high-25fps.mp4     1080p, probably too much for SYNC
06-800x480-mpeg4-25fps.mp4           MPEG-4 Part 2, a fallback

In the developer's car (2026-10): the 800x480 H.264 files play fine, 720p and 1080p
glitch, sound and colours are right, and the beep comes slightly off the flash (the
files are in step; the offset is the player's).

For each file, note:
  - Does it play at all?
  - Smooth, or stuttering? The clock in the top left corner shows the time.
  - Sound from the car's speakers? Left and right the right way round (file 01)?
  - Do the beep and the white flash happen together?
  - Does the volume knob work?
  - After Close/Exit, does SYNC come back?
