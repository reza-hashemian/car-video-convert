#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_convert_gui.py — رابط گرافیکی تبدیل ویدیو برای هد‌یونیت خودرو

طرز استفاده:
    دابل‌کلیک روی همین فایل. یا:

        python car_convert_gui.py

موتور تبدیل همان car_convert.py است — این فایل فقط یک پوسته‌ی گرافیکی
روی آن است. هر دو فایل باید کنار هم باشند.

برای کسی نوشته شده که با ترمینال کار نمی‌کند: فیلم‌ها را انتخاب می‌کند،
از فهرست، کیفیتی را که روی دستگاهش جواب می‌دهد برمی‌دارد، و دکمه را
می‌زند.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# موتور تبدیل از فایل کنار دستی خوانده می‌شود.
try:
    import car_convert as engine
except ImportError:
    # پیام قابل فهم، نه استک‌تریس.
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "فایل ناقص",
        "فایل car_convert.py پیدا نشد.\n\n"
        "این دو فایل باید کنار هم باشند:\n"
        "    car_convert.py\n"
        "    car_convert_gui.py",
    )
    sys.exit(2)


# --------------------------------------------------------------------------
# رزولوشن‌های پیشنهادی
#
# ترتیب از بزرگ به کوچک. کاربر از بالا شروع می‌کند و اگر دستگاهش ارور
# داد یکی پایین‌تر را امتحان می‌کند. همه مضرب ۱۶ هستند — دیکودرهای
# MPEG-4 ASP به هم‌ترازی ماکروبلاک نیاز دارند.
# --------------------------------------------------------------------------

PRESETS: list[tuple[str, int, int, str]] = [
    ("640 x 480", 640, 480, "(1)"),
    ("640 x 360", 640, 360, "(2)"),
    ("480 x 360", 480, 360, "(3)"),
    ("320 x 240", 320, 240, "(4)"),
]

WINDOW_TITLE = "تبدیل ویدیو برای خودرو"


def format_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f}{unit}" if unit != "GB" else f"{num_bytes:.1f}GB"
        num_bytes /= 1024
    return f"{num_bytes:.1f}GB"


class ConverterGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.files: list[Path] = []
        self.out_dir: Path | None = None
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.events: queue.Queue = queue.Queue()

        root.title(WINDOW_TITLE)
        root.geometry("720x620")
        root.minsize(640, 560)

        self._build_widgets()
        self._check_ffmpeg()
        self._pump_events()

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- ساخت رابط

    def _build_widgets(self) -> None:
        pad = {"padx": 12, "pady": 6}

        # --- مرحله ۱: انتخاب فایل
        step1 = ttk.LabelFrame(self.root, text=" 1 - Videos / فیلم‌ها ")
        step1.pack(fill="both", expand=True, **pad)

        bar = ttk.Frame(step1)
        bar.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Button(bar, text="+ Video / فیلم",
                   command=self.add_files).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="+ Folder / پوشه",
                   command=self.add_folder).pack(side="right", padx=(4, 0))
        self.remove_btn = ttk.Button(bar, text="− Remove",
                                     command=self.remove_selected,
                                     state="disabled")
        self.remove_btn.pack(side="right", padx=(4, 0))
        self.clear_btn = ttk.Button(bar, text="Clear",
                                    command=self.clear_files, state="disabled")
        self.clear_btn.pack(side="right", padx=(4, 0))

        list_wrap = ttk.Frame(step1)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scroll = ttk.Scrollbar(list_wrap, orient="vertical")
        self.listbox = tk.Listbox(list_wrap, selectmode="extended",
                                  yscrollcommand=scroll.set,
                                  activestyle="none", height=8)
        scroll.config(command=self.listbox.yview)
        scroll.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        self.count_label = ttk.Label(step1, text="no videos yet")
        self.count_label.pack(anchor="w", padx=10, pady=(0, 8))

        # --- مرحله ۲: کیفیت
        step2 = ttk.LabelFrame(self.root, text=" 2 - Size / اندازه ")
        step2.pack(fill="x", **pad)

        self.preset_var = tk.IntVar(value=0)
        for index, (label, _w, _h, hint) in enumerate(PRESETS):
            row = ttk.Frame(step2)
            row.pack(fill="x", padx=8, pady=1)
            text = f"{hint}  {label}"
            if index == 0:
                text += "   ★"
            ttk.Radiobutton(row, text=text, value=index,
                            variable=self.preset_var).pack(side="left")

        # نکته: Tk روی لینوکس حروف فارسی را به هم نمی‌چسباند، برای همین
        # متن‌های بلند فارسی اینجا عمداً استفاده نشده‌اند. عددها و
        # نشانه‌ها در هر حالتی درست دیده می‌شوند.
        note = ttk.Label(
            step2,
            text="★ = try this first        "
                 "error on car screen?  ->  pick the next one down",
            foreground="#444", justify="left")
        note.pack(anchor="w", padx=10, pady=(4, 8))

        # --- مرحله ۳: ساخت
        step3 = ttk.Frame(self.root)
        step3.pack(fill="x", **pad)

        self.start_btn = ttk.Button(step3, text="  ▶  START / شروع  ",
                                    command=self.start, state="disabled")
        self.start_btn.pack(side="right")

        self.cancel_btn = ttk.Button(step3, text="Cancel", command=self.cancel,
                                     state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 6))

        self.open_btn = ttk.Button(step3, text="📂 Open output folder",
                                   command=self.open_output, state="disabled")
        self.open_btn.pack(side="left")

        # --- وضعیت
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=(0, 4))

        self.status = ttk.Label(self.root, text="ready", anchor="w")
        self.status.pack(fill="x", padx=12)

        log_wrap = ttk.Frame(self.root)
        log_wrap.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical")
        self.log_box = tk.Text(log_wrap, height=7, wrap="word",
                               yscrollcommand=log_scroll.set,
                               state="disabled", background="#f7f7f7")
        log_scroll.config(command=self.log_box.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

    # ---------------------------------------------------------------- بررسی ffmpeg

    def _check_ffmpeg(self) -> None:
        self.ffmpeg = engine.find_tool("ffmpeg")
        self.ffprobe = engine.find_tool("ffprobe")
        if self.ffmpeg and self.ffprobe:
            return

        self.start_btn.config(state="disabled")
        self.log("[!] ffmpeg not found - conversion is not possible")
        messagebox.showerror(
            "ffmpeg نصب نیست",
            "برنامه برای تبدیل به ffmpeg نیاز دارد و پیدایش نکرد.\n\n"
            "ویندوز:\n"
            "    در Command Prompt بزنید:\n"
            "    winget install Gyan.FFmpeg\n"
            "    بعد این برنامه را ببندید و دوباره باز کنید.\n\n"
            "لینوکس:\n"
            "    sudo apt install ffmpeg\n\n"
            "یا پوشه‌ی bin مربوط به ffmpeg را کنار همین برنامه کپی کنید.",
        )

    # ---------------------------------------------------------------- فایل‌ها

    def add_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(engine.VIDEO_EXTS))
        chosen = filedialog.askopenfilenames(
            title="فیلم‌ها را انتخاب کنید",
            filetypes=[("فایل‌های ویدیویی", patterns), ("همه‌ی فایل‌ها", "*.*")],
        )
        self._add([Path(c) for c in chosen])

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="پوشه‌ی فیلم‌ها را انتخاب کنید")
        if not folder:
            return
        found = engine.collect_files(Path(folder))
        if not found:
            messagebox.showinfo("خالی",
                                "در این پوشه فایل ویدیویی پیدا نشد.")
            return
        self._add(found)

    def _add(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            if path.suffix.lower() not in engine.VIDEO_EXTS:
                continue
            if path in self.files:
                continue
            self.files.append(path)
            self.listbox.insert("end", f"  {path.name}")
            added += 1
        if added:
            self.log(f"+ {added} file(s)")
        self._refresh_counts()

    def remove_selected(self) -> None:
        for index in sorted(self.listbox.curselection(), reverse=True):
            self.listbox.delete(index)
            del self.files[index]
        self._refresh_counts()

    def clear_files(self) -> None:
        self.listbox.delete(0, "end")
        self.files.clear()
        self._refresh_counts()

    def _on_select(self, _event=None) -> None:
        has = bool(self.listbox.curselection())
        self.remove_btn.config(state="normal" if has else "disabled")

    def _refresh_counts(self) -> None:
        count = len(self.files)
        if count:
            total = sum(f.stat().st_size for f in self.files if f.exists())
            self.count_label.config(
                text=f"{count} videos  /  {format_size(total)}")
        else:
            self.count_label.config(text="no videos yet")

        busy = self.worker is not None and self.worker.is_alive()
        ready = count > 0 and not busy and bool(self.ffmpeg)
        self.start_btn.config(state="normal" if ready else "disabled")
        self.clear_btn.config(state="normal" if count and not busy else "disabled")
        self._on_select()

    # ---------------------------------------------------------------- اجرا

    def start(self) -> None:
        if not self.files:
            return

        index = self.preset_var.get()
        _label, width, height, _hint = PRESETS[index]

        # خروجی کنار اولین فیلم ساخته می‌شود — همان‌جایی که کاربر دنبالش
        # می‌گردد. زیرپوشه‌ی جدا برای هر رزولوشن تا نتایج قاطی نشوند و
        # امتحان کردن رزولوشن بعدی، قبلی را پاک نکند.
        out_dir = self.files[0].parent / f"{engine.OUTPUT_DIRNAME}_{width}x{height}"
        try:
            out_dir.mkdir(exist_ok=True)
        except OSError as exc:
            messagebox.showerror("ساخت پوشه ممکن نشد", str(exc))
            return
        self.out_dir = out_dir

        self.cancel_flag.clear()
        self.progress.config(maximum=len(self.files), value=0)
        self.start_btn.config(state="disabled")
        self.clear_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.open_btn.config(state="normal")

        self.log("")
        self.log(f"START  {width}x{height}  -  {len(self.files)} file(s)")
        self.log(f"output: {out_dir}")

        self.worker = threading.Thread(
            target=self._convert_all,
            args=(list(self.files), out_dir, width, height),
            daemon=True,
        )
        self.worker.start()

    def _convert_all(self, files: list[Path], out_dir: Path,
                     width: int, height: int) -> None:
        """در نخ جداگانه اجرا می‌شود — هیچ‌وقت مستقیم به رابط دست نمی‌زند."""
        done = failed = skipped = 0
        used: set[str] = set()
        started = time.time()

        for index, src in enumerate(files, 1):
            if self.cancel_flag.is_set():
                self._emit("log", "cancelled")
                break

            dst = engine.unique_target(
                out_dir, engine.safe_stem(src.stem, index), used)

            self._emit("status", f"[{index}/{len(files)}] {src.name}")

            if dst.exists() and dst.stat().st_size > 0:
                self._emit("log", f"[{index}] {src.name} - already done, skipped")
                skipped += 1
                self._emit("progress", index)
                continue

            duration = engine.probe_duration(self.ffprobe, src)
            audio = engine.has_audio(self.ffprobe, src)
            crop = None
            if engine.CROP_DETECT:
                crop = engine.detect_crop(
                    self.ffmpeg, src, duration,
                    engine.probe_size(self.ffprobe, src))

            tmp = dst.with_name(dst.name + ".part")
            cmd = engine.build_command(self.ffmpeg, src, tmp, audio, crop,
                                       size=(width, height))
            file_started = time.time()
            result = engine.run(cmd)

            if self.cancel_flag.is_set():
                tmp.unlink(missing_ok=True)
                self._emit("log", "cancelled")
                break

            if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                tmp.unlink(missing_ok=True)
                detail = (result.stderr or "").strip().splitlines()
                reason = detail[-1] if detail else "unknown error"
                self._emit("log", f"[{index}] FAILED {src.name} - {reason}")
                failed += 1
                self._emit("progress", index)
                continue

            out_duration = engine.probe_duration(self.ffprobe, tmp)
            if duration > 0 and out_duration > 0 and out_duration < duration * 0.95:
                tmp.unlink(missing_ok=True)
                self._emit("log", f"[{index}] FAILED {src.name} - incomplete output")
                failed += 1
                self._emit("progress", index)
                continue

            tmp.replace(dst)
            note = "  (black bars removed)" if crop else ""
            self._emit("log",
                       f"[{index}] OK  {dst.name}  "
                       f"({format_size(dst.stat().st_size)}, "
                       f"{engine.human_time(time.time() - file_started)}){note}")
            done += 1
            self._emit("progress", index)

        self._emit("finished", {
            "done": done, "failed": failed, "skipped": skipped,
            "elapsed": time.time() - started,
            "cancelled": self.cancel_flag.is_set(),
        })

    def cancel(self) -> None:
        self.cancel_flag.set()
        self.cancel_btn.config(state="disabled")
        self.status.config(text="cancelling after current file...")

    # ---------------------------------------------------------------- پل نخ‌ها

    def _emit(self, kind: str, payload) -> None:
        self.events.put((kind, payload))

    def _pump_events(self) -> None:
        """صف نخ کارگر را خالی می‌کند. فقط همین‌جا به رابط دست می‌زنیم."""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "status":
                    self.status.config(text=payload)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "finished":
                    self._on_finished(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._pump_events)

    def _on_finished(self, stats: dict) -> None:
        self.cancel_btn.config(state="disabled")
        self._refresh_counts()

        summary = (f"done: {stats['done']}    "
                   f"skipped: {stats['skipped']}    "
                   f"failed: {stats['failed']}    "
                   f"time: {engine.human_time(stats['elapsed'])}")
        self.status.config(text=summary)
        self.log("─" * 50)
        self.log(summary)

        if stats["cancelled"]:
            return

        if stats["done"] or stats["skipped"]:
            messagebox.showinfo(
                "تمام شد",
                f"{stats['done']} فیلم ساخته شد.\n\n"
                f"پوشه‌ی خروجی:\n{self.out_dir}\n\n"
                "محتویات این پوشه را روی فلش کپی کنید.\n\n"
                "یادتان باشد قبل از کشیدن فلش، eject بزنید.",
            )
        elif stats["failed"]:
            messagebox.showwarning(
                "ناموفق",
                "هیچ فیلمی ساخته نشد. جزئیات خطا در پایین پنجره است.",
            )

    # ---------------------------------------------------------------- کمکی

    def log(self, message: str) -> None:
        self.log_box.config(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def open_output(self) -> None:
        if not self.out_dir or not self.out_dir.exists():
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(self.out_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.out_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self.out_dir)])
        except OSError as exc:
            messagebox.showerror("باز کردن پوشه ممکن نشد", str(exc))

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                    "هنوز تمام نشده",
                    "تبدیل در حال انجام است. واقعاً ببندم؟"):
                return
            self.cancel_flag.set()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    ConverterGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
