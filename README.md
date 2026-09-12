# car-video-convert

Batch-convert any video into the one format a stubborn car head unit will
actually play. Drop the script next to your videos, run it with no arguments,
and copy the output folder to a USB stick.

Built to solve a real problem: a Hyundai Sonata head unit that rejected every
file thrown at it — `Not supported` for some, `Damaged` for others — until the
exact working profile was found by isolating one variable at a time.

---

## Quick start

### Graphical version (no terminal needed)

Two GUIs are provided; both wrap the same engine.

**Qt version — recommended** (`car_convert_qt.py`). Needs `pip install PySide6`.
Renders Persian/Arabic text correctly and has a cleaner layout.

```bash
pip install PySide6
python car_convert_qt.py
```

**tkinter version** (`car_convert_gui.py`). No install needed — tkinter ships
with Python — but Tk on Linux does not shape Arabic-script text, so its labels
are kept short and bilingual.

```bash
python car_convert_gui.py
```

Pick the videos, pick a size, press START. Output lands in a folder named
after the size you chose — `CAR_READY_640x480/` and so on — next to the first
video, so trying a second size never overwrites the first attempt.

The size list is ordered largest first. Start at the top; if the head unit
shows an error, pick the next one down and convert again. The GUI file must sit in the same folder as `car_convert.py` — it is
only a shell around that engine.

### Command-line version

```bash
# put car_convert.py in the folder with your videos, then:
python car_convert.py
```

No flags. No config. Output lands in `CAR_READY/` next to the script.

On Windows you can double-click the file — the window stays open so you can
read the result.

**Requires:** Python 3.8+ and [ffmpeg](https://ffmpeg.org/) (`ffmpeg` and
`ffprobe`) on your `PATH`.

```bash
# Windows
winget install Gyan.FFmpeg     # then close and reopen the terminal

# Debian / Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

No install? Drop ffmpeg's `bin` folder next to `car_convert.py` — the script
looks there too, which makes the whole thing portable on a USB stick.

---

## What it does

Every input becomes an AVI with this profile:

| | |
|---|---|
| Container | AVI |
| Video | Xvid (MPEG-4 Simple Profile), tag `xvid` |
| Resolution | 640×480 |
| Frame rate | 25 fps, constant |
| Audio | MP3 stereo, 44100 Hz, 128 kbps |
| B-frames | none |

Portrait video is **pillarboxed**, not cropped: it fills the full height of
the screen — touching top and bottom — and only the left and right get black
padding, which keeps the aspect ratio intact so the unit doesn't reject it.
Nothing gets cut off, nothing gets stretched. Padding never appears on all
four sides.

Black bars already baked into the source file are **detected and removed**
before scaling. Without this, a clip that was letterboxed by some other app
would get our padding on top of its own bars and end up black on all four
sides.

**Input format doesn't matter. Output is always AVI.** Feed it MP4, MKV, MOV,
WMV, FLV, TS, WebM, 3GP, M2TS, or AVI — you get AVI back. That's deliberate:
the head unit this was built for reports `Not supported` on MP4/H.264 but
plays Xvid AVI fine.

---

## Why these exact numbers

Head units are not media players. They run fixed-function decoders with hard
limits, and they fail in unhelpful ways. The profile above came out of a
controlled test: eight files, each changing exactly one variable, played on
the actual dashboard.

What the testing established:

- **Portrait video is the main killer.** Unconverted phone video (608×1080,
  720×1280) is refused outright. Of 23 files, the only two that played were
  the two landscape ones — hence padding everything into a landscape frame.
- **There is a resolution ceiling, and 1280×720 is above it.** 640×480 and
  640×360 played; 1280×720 produced `Damaged`.
- **640×480 is the tallest frame the unit accepts.** That matters most for
  portrait video: in a 640×360 box a vertical clip is scaled down to a small
  strip in the middle, but at 640×480 it gets a third more height and fills
  the panel properly.
- **Cropping to fill looks wrong.** The one test file that cropped instead of
  padding was visibly wrong on screen. Padding won.
- **Dimensions should be multiples of 16.** Many MPEG-4 ASP decoders require
  macroblock alignment; 854, 1080 and 606 are not.
- **Constant frame rate matters.** AVI cannot express variable frame rate, and
  sources like `14989/500` (29.978 fps) desync or get rejected.

Two error messages, two distinct causes — worth knowing if you're debugging
your own unit:

| Message | Meaning |
|---|---|
| `Not supported` | Container/codec not recognised at all (e.g. MP4/H.264) |
| `Damaged` | Container recognised, but the decoder can't handle the parameters |

`Damaged` rarely means the file is actually broken. Verify with
`ffmpeg -v error -i FILE -f null -` before assuming corruption.

---

## Uses beyond the car

The script is really "normalise anything into a maximally compatible video,"
which is useful wherever a decoder is old, fixed-function, or fussy:

- **Older TVs and DVD/Blu-ray players** with USB playback. Same class of
  decoder, same constraints.
- **Digital photo frames and cheap media boxes**, which usually top out well
  below 720p.
- **In-flight entertainment and hotel screens**, and other embedded players
  where you get one shot at a format that works.
- **Airing phone-shot vertical video on any landscape screen** without a
  player that letterboxes for you.
- **Projectors and old classroom AV kit** still fed from a USB stick.
- **Shrinking a library for a small stick** — 330 minutes of source came out
  around 1.5 GB in testing.
- **Normalising mixed footage before editing**, when you want one resolution,
  one frame rate, one audio rate across clips from many sources.
- **Retro and embedded devices** (handhelds, e-ink readers, hobbyist boards)
  that ship MPEG-4 ASP decoders.

For a modern phone, laptop, or smart TV you don't need this — those play
almost anything, and you'd be throwing away quality for no reason.

---

## Tuning

If your device differs, edit the constants at the top of `car_convert.py`:

```python
BOX_WIDTH = 640        # output width
BOX_HEIGHT = 480       # output height
FPS = 25               # constant frame rate
AUDIO_RATE = 44100     # Hz
AUDIO_BITRATE = 128    # kbps
VIDEO_QUALITY = 4      # Xvid quality: lower is better; 2–6 is sensible

CROP_DETECT = True     # strip black bars baked into the source
CROP_SCAN_SECONDS = 12 # how much footage to scan when detecting them
CROP_LIMIT = 24        # black threshold, 0–255; higher is stricter
CROP_MIN_BAR = 32      # bars thinner than this many pixels are ignored
```

Keep width and height multiples of 16.

Finding the profile for a *different* device is the same method that produced
this one: get one file playing, then change one variable at a time. Start
small — 480×360 at 25 fps — and work up. Guessing a high resolution and
working down wastes time, because everything above the ceiling fails
identically.

---

## Behaviour worth knowing

**Re-running is safe.** Files already in `CAR_READY/` are skipped, so an
interrupted run picks up where it left off — just run it again.

**Interrupted encodes leave nothing behind.** Each file is written to `.part`
and only moved into place when complete.

**Truncated output is rejected.** Every result is probed and its duration
compared against the source; anything under 95% is deleted and reported as a
failure rather than handed back as a success.

**Filenames are sanitised.** `A (13).avi` becomes `A _13.avi`. Names that are
entirely non-ASCII (Persian, Arabic, CJK) reduce to nothing, so those get a
positional fallback: `video_07.avi`. Collisions get a numeric suffix.

**Silent videos work.** Audio is mapped only when present.

**One folder only.** Subdirectories are not searched.

---

## Speed

Xvid encodes on CPU — there is no GPU encoder for it, so a fast graphics card
doesn't help. Expect roughly 4–5× realtime on a modern desktop CPU: a 45
second clip took about 10 seconds in testing, and 330 minutes of video took
around 75 minutes.

---

## Troubleshooting

**`ffmpeg not found`** — Install it, or drop its `bin` folder next to the
script. On Windows, close and reopen the terminal after installing; `PATH` is
only read at startup.

**Files still won't play** — Your unit's ceiling may be lower. Try 480×360,
then 320×240. Also try putting files in the USB root rather than a subfolder;
some units don't recurse.

**USB stick becomes read-only** — This happens after pulling the stick without
ejecting. The filesystem's dirty bit gets set and the kernel remounts
read-only to protect data:

```bash
sudo umount /dev/sdX1
sudo fsck.vfat -a -w /dev/sdX1
# then physically unplug and replug
```

Run `fsck` on an *unmounted* filesystem — repairs on a live mount aren't
reliable. Eject properly next time.

**Head unit doesn't see the stick** — Format as FAT32. Many units don't read
exFAT or NTFS. Note FAT32's 4 GB per-file limit.

---

## License

MIT
