#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_convert.py — تبدیل ویدیو برای پخش روی هد‌یونیت هیوندای سوناتا

طرز استفاده:
    این فایل را کنار ویدیوها بگذارید و اجرا کنید. تمام.

        python car_convert.py

    ویندوز: دابل‌کلیک روی فایل هم کار می‌کند.

خروجی در زیرپوشه‌ی CAR_READY/ ساخته می‌شود.

پروفایل خروجی (روی سوناتا ۲۰۱۴ تست و تأیید شده):
    640x480 · Xvid Simple Profile · تگ 'xvid' · DAR 4:3
    25 fps ثابت · MP3 استریو 44100 Hz · بدون B-frame

چرا دقیقاً همین اعداد: ویدیوهای عمودی موبایل (608x1080 و مانند آن) روی
هد‌یونیت پیام damaged می‌دهند. تست تک‌متغیره نشان داد دستگاه تا 640x480
را قبول می‌کند، ولی 1280x720 را رد می‌کند. قاب 640x480 انتخاب شده چون
بلندترین ارتفاعی است که دستگاه می‌پذیرد — یعنی ویدیوی عمودی بیشترین
تصویر ممکن را می‌گیرد و روی صفحه کوچک به نظر نمی‌رسد.

تصویر داخل قاب pad می‌شود (نه crop) تا چیزی بریده نشود. ویدیوی عمودی
ارتفاعش کامل می‌شود — به سقف و کف صفحه می‌چسبد — و فقط چپ و راستش
پدینگ می‌گیرد تا نسبت تصویر حفظ شود و دستگاه ارور ندهد.

نوار سیاهی که خودِ فایل منبع دارد قبل از این کار با cropdetect بریده
می‌شود، وگرنه پدینگ ما روی سیاهیِ خودش می‌نشیند و نتیجه از هر چهار طرف
سیاه می‌شود.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# پروفایل تست‌شده — بدون دلیل محکم تغییر ندهید
# --------------------------------------------------------------------------

BOX_WIDTH = 640
BOX_HEIGHT = 480
FPS = 25
AUDIO_RATE = 44100
AUDIO_BITRATE = 128
VIDEO_QUALITY = 4          # کیفیت Xvid: کمتر = بهتر (۲ تا ۶ منطقی است)

# تشخیص نوار سیاهِ داخل خود فایل منبع
CROP_DETECT = True         # False کنید تا نوارها دست‌نخورده بمانند
CROP_SCAN_SECONDS = 12     # چند ثانیه از فیلم برای تشخیص اسکن شود
CROP_LIMIT = 24            # آستانه‌ی سیاهی (۰ تا ۲۵۵)؛ بالاتر = سخت‌گیرتر
CROP_MIN_BAR = 32          # نوار کمتر از این تعداد پیکسل نادیده گرفته می‌شود

OUTPUT_DIRNAME = "CAR_READY"

VIDEO_EXTS = {
    ".avi", ".mkv", ".mp4", ".m4v", ".mpg", ".mpeg", ".mov", ".wmv",
    ".flv", ".ts", ".webm", ".3gp", ".divx", ".m2ts", ".mts", ".asf",
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def human_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def find_tool(name: str) -> str | None:
    """ffmpeg/ffprobe را در PATH یا کنار خود اسکریپت پیدا می‌کند."""
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return found
    # حالت قابل حمل: پوشه‌ی bin کنار اسکریپت (مفید روی فلش)
    here = Path(__file__).resolve().parent
    for candidate in (here / name, here / f"{name}.exe",
                      here / "bin" / name, here / "bin" / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return None


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def probe_duration(ffprobe: str, path: Path) -> float:
    """مدت فایل بر حسب ثانیه. صفر یعنی نامشخص."""
    result = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                  "-of", "json", str(path)])
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0.0


def has_audio(ffprobe: str, path: Path) -> bool:
    result = run([ffprobe, "-v", "error", "-select_streams", "a",
                  "-show_entries", "stream=index", "-of", "json", str(path)])
    if result.returncode != 0:
        return False
    try:
        return bool(json.loads(result.stdout).get("streams"))
    except json.JSONDecodeError:
        return False


def probe_size(ffprobe: str, path: Path) -> tuple[int, int]:
    """ابعاد تصویر منبع. (0, 0) یعنی نامشخص."""
    result = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height", "-of", "json",
                  str(path)])
    if result.returncode != 0:
        return (0, 0)
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return (int(stream["width"]), int(stream["height"]))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return (0, 0)


def detect_crop(ffmpeg: str, src: Path, duration: float,
                source_size: tuple[int, int] = (0, 0)) -> str | None:
    """
    نوارهای سیاهِ پخته‌شده در خود فایل منبع را پیدا می‌کند.

    خیلی از ویدیوها (مثلاً افقی‌هایی که داخل قاب عمودی اینستاگرام ذخیره
    شده‌اند) خودشان نوار سیاه دارند. اگر آن‌ها را نبریم، پدینگِ ما روی
    سیاهیِ خودشان می‌نشیند و نتیجه از هر چهار طرف سیاه می‌شود.

    خروجی: رشته‌ی crop=w:h:x:y — یا None اگر چیزی برای بریدن نبود.
    """
    # از ثانیه‌ی ۳ شروع می‌کنیم تا فید-این و لوگوی ابتدای فیلم
    # باعث تشخیص اشتباه نشود.
    start = 3.0 if duration > CROP_SCAN_SECONDS + 4 else 0.0

    result = run([
        ffmpeg, "-hide_banner", "-nostats",
        "-ss", str(start), "-t", str(CROP_SCAN_SECONDS), "-i", str(src),
        "-vf", f"cropdetect=limit={CROP_LIMIT}:round=16:reset=0",
        "-an", "-sn", "-f", "null", "-",
    ])

    # cropdetect روی stderr گزارش می‌دهد؛ آخرین خط پایدارترین حدس است.
    crop = None
    for line in (result.stderr or "").splitlines():
        marker = line.rfind("crop=")
        if marker != -1:
            crop = line[marker:].strip()
    if not crop:
        return None

    try:
        w, h, x, y = (int(v) for v in crop[len("crop="):].split(":"))
    except ValueError:
        return None

    # ابعاد بی‌معنی را قبول نمی‌کنیم (گاهی روی فیلم تماماً تاریک رخ می‌دهد).
    if w < 16 or h < 16:
        return None
    if x < 0 or y < 0:
        return None

    # cropdetect با round=16 چند پیکسل را هم گرد می‌کند. برای اینکه بُرش‌های
    # بی‌اثر را گزارش نکنیم، فقط وقتی نوار را واقعی می‌دانیم که از یک آستانه
    # بزرگ‌تر باشد.
    src_w, src_h = source_size
    if src_w and src_h:
        trimmed_x = src_w - w
        trimmed_y = src_h - h
        if trimmed_x < CROP_MIN_BAR and trimmed_y < CROP_MIN_BAR:
            return None

    return f"crop={w}:{h}:{x}:{y}"


def build_command(ffmpeg: str, src: Path, dst: Path, audio: bool,
                  crop: str | None = None,
                  size: tuple[int, int] | None = None) -> list[str]:
    # اول نوار سیاهِ خودِ منبع بریده می‌شود (اگر داشته باشد)، بعد تصویر
    # داخل قاب جا می‌شود و فضای باقی‌مانده مشکی پر می‌شود.
    #
    # force_original_aspect_ratio=decrease یعنی تصویر با بُعدِ تنگ‌تر جا
    # می‌شود: ویدیوی عمودی ارتفاعش کامل می‌شود (به سقف و کف می‌چسبد) و
    # فقط چپ و راست پد می‌گیرد؛ ویدیوی خیلی پهن برعکس. هیچ‌وقت هر چهار
    # طرف پد نمی‌شود.
    # رابط گرافیکی می‌تواند رزولوشن دیگری بدهد؛ پیش‌فرض همان پروفایل بالاست.
    box_w, box_h = size if size else (BOX_WIDTH, BOX_HEIGHT)

    steps = []
    if crop:
        steps.append(crop)
    steps += [
        f"scale=w={box_w}:h={box_h}:force_original_aspect_ratio=decrease",
        f"pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
        "format=yuv420p",
        f"fps={FPS}",
    ]
    filters = ",".join(steps)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
    cmd += ["-map", "0:v:0"]
    if audio:
        cmd += ["-map", "0:a:0"]
    cmd += ["-sn", "-dn", "-map_chapters", "-1"]
    cmd += ["-vf", filters]
    cmd += [
        "-c:v", "libxvid",
        "-vtag", "xvid",        # حروف کوچک — مطابق فایلی که روی دستگاه کار می‌کند
        "-q:v", str(VIDEO_QUALITY),
        "-bf", "0",             # بدون B-frame؛ دیکودرهای قدیمی گیر می‌کنند
        "-flags", "+mv4",
        "-mbd", "rd",
        "-trellis", "0",
        "-g", str(FPS * 2),
    ]
    if audio:
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{AUDIO_BITRATE}k",
                "-ac", "2", "-ar", str(AUDIO_RATE)]
    cmd += ["-max_muxing_queue_size", "1024", "-f", "avi", str(dst)]
    return cmd


def safe_stem(name: str, index: int) -> str:
    """
    اسم ساده و بدون کاراکتر دردسرساز برای هد‌یونیت.

    اسم‌های کاملاً غیرانگلیسی (مثلاً فارسی) بعد از پاک‌سازی چیزی باقی
    نمی‌گذارند، پس در آن حالت از شماره‌ی ردیف استفاده می‌کنیم تا فایل
    همچنان قابل تشخیص بماند.
    """
    keep = []
    for ch in name:
        if ch.isascii() and (ch.isalnum() or ch in "._- "):
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip(" ._-")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned or f"video_{index:02d}"


def unique_target(out_dir: Path, stem: str, used: set[str]) -> Path:
    """از برخورد اسم‌ها جلوگیری می‌کند (مثلاً وقتی چند فایل به یک اسم ساده می‌رسند)."""
    base = stem
    counter = 2
    while stem.lower() in used:
        stem = f"{base}_{counter}"
        counter += 1
    used.add(stem.lower())
    return out_dir / f"{stem}.avi"


def collect_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.name.startswith(".")
    )


def main() -> int:
    # پوشه‌ی خود اسکریپت — نه پوشه‌ی جاری ترمینال.
    # اینطور دابل‌کلیک روی ویندوز هم درست کار می‌کند.
    root = Path(__file__).resolve().parent

    log("=" * 58)
    log("  تبدیل ویدیو برای هد‌یونیت خودرو")
    log("=" * 58)
    log(f"پوشه   : {root}")

    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        log()
        log("[!] ffmpeg پیدا نشد.")
        log()
        log("    ویندوز : winget install Gyan.FFmpeg")
        log("             (بعدش پنجره‌ی ترمینال را ببندید و دوباره باز کنید)")
        log("    لینوکس : sudo apt install ffmpeg")
        log()
        log("    یا: پوشه‌ی bin مربوط به ffmpeg را کنار همین فایل کپی کنید.")
        return 2

    files = collect_files(root)
    if not files:
        log()
        log("[!] هیچ فایل ویدیویی در این پوشه پیدا نشد.")
        log("    این اسکریپت را کنار ویدیوها بگذارید و دوباره اجرا کنید.")
        return 1

    out_dir = root / OUTPUT_DIRNAME
    out_dir.mkdir(exist_ok=True)

    log(f"خروجی  : {out_dir.name}/")
    log(f"پروفایل: {BOX_WIDTH}x{BOX_HEIGHT} · Xvid · {FPS}fps · MP3 {AUDIO_RATE}Hz")
    log(f"تعداد  : {len(files)} فایل")
    log("-" * 58)

    done = failed = skipped = 0
    problems: list[str] = []
    used_names: set[str] = set()
    started = time.time()

    for index, src in enumerate(files, 1):
        dst = unique_target(out_dir, safe_stem(src.stem, index), used_names)

        if dst.exists() and dst.stat().st_size > 0:
            log(f"[{index}/{len(files)}] {src.name} — قبلاً ساخته شده، رد شد")
            skipped += 1
            continue

        log(f"[{index}/{len(files)}] {src.name}")
        source_duration = probe_duration(ffprobe, src)
        audio = has_audio(ffprobe, src)

        crop = (detect_crop(ffmpeg, src, source_duration,
                            probe_size(ffprobe, src))
                if CROP_DETECT else None)
        if crop:
            log(f"          نوار سیاه منبع حذف شد ({crop[len('crop='):]})")

        # ابتدا در فایل موقت می‌نویسیم تا قطع‌شدن وسط کار،
        # خروجی ناقص به جا نگذارد.
        tmp = dst.with_name(dst.name + ".part")
        file_started = time.time()
        result = run(build_command(ffmpeg, src, tmp, audio, crop))

        if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            detail = (result.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else "خطای نامشخص ffmpeg"
            log(f"          ✗ ناموفق — {reason}")
            problems.append(f"{src.name}: {reason}")
            failed += 1
            continue

        # مدت خروجی را با مبدأ می‌سنجیم؛ فایل بریده را قبول نمی‌کنیم.
        out_duration = probe_duration(ffprobe, tmp)
        if source_duration > 0 and out_duration > 0 and out_duration < source_duration * 0.95:
            tmp.unlink(missing_ok=True)
            reason = (f"خروجی ناقص ({human_time(out_duration)} از "
                      f"{human_time(source_duration)})")
            log(f"          ✗ {reason}")
            problems.append(f"{src.name}: {reason}")
            failed += 1
            continue

        tmp.replace(dst)
        size_mb = dst.stat().st_size / (1024 * 1024)
        log(f"          ✓ {dst.name}  ({size_mb:.0f}MB, "
            f"{human_time(time.time() - file_started)})")
        done += 1

    log("-" * 58)
    log(f"موفق: {done}   رد شده: {skipped}   ناموفق: {failed}   "
        f"زمان: {human_time(time.time() - started)}")

    if problems:
        log()
        log("فایل‌های ناموفق:")
        for item in problems:
            log(f"  - {item}")

    if done or skipped:
        log()
        log(f"فایل‌ها آماده‌اند در: {out_dir}")
        log("محتویات این پوشه را روی فلش کپی کنید.")
        log()
        log("نکته: قبل از کشیدن فلش حتماً eject بزنید،")
        log("      وگرنه فلش دفعه‌ی بعد read-only می‌شود.")

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        log()
        log("متوقف شد. فایل‌های .part ناقص را می‌توانید پاک کنید.")
        code = 130

    # روی ویندوز با دابل‌کلیک، پنجره نباید فوری بسته شود.
    if sys.platform == "win32" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nEnter را بزنید...")
        except (EOFError, KeyboardInterrupt):
            pass

    sys.exit(code)
