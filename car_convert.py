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
    640x360 · Xvid Simple Profile · تگ 'xvid' · DAR 16:9
    25 fps ثابت · MP3 استریو 44100 Hz · بدون B-frame

چرا دقیقاً همین اعداد: ویدیوهای عمودی موبایل (608x1080 و مانند آن) روی
هد‌یونیت پیام damaged می‌دهند. تست تک‌متغیره نشان داد دستگاه تا 640x480
و نسبت 16:9 را قبول می‌کند، ولی 1280x720 را رد می‌کند. تصویر داخل قاب
افقی pad می‌شود (نه crop) تا چیزی از کادر بریده نشود.
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
BOX_HEIGHT = 360
FPS = 25
AUDIO_RATE = 44100
AUDIO_BITRATE = 128
VIDEO_QUALITY = 4          # کیفیت Xvid: کمتر = بهتر (۲ تا ۶ منطقی است)

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


def build_command(ffmpeg: str, src: Path, dst: Path, audio: bool) -> list[str]:
    # تصویر داخل قاب افقی جا می‌شود و باقی با مشکی پر می‌شود.
    # pad و نه crop — تا از کادر چیزی بریده نشود.
    filters = (
        f"scale=w={BOX_WIDTH}:h={BOX_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={BOX_WIDTH}:{BOX_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,format=yuv420p,fps={FPS}"
    )

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

        # ابتدا در فایل موقت می‌نویسیم تا قطع‌شدن وسط کار،
        # خروجی ناقص به جا نگذارد.
        tmp = dst.with_name(dst.name + ".part")
        file_started = time.time()
        result = run(build_command(ffmpeg, src, tmp, audio))

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
