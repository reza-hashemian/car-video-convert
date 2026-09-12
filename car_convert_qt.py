#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_convert_qt.py — رابط گرافیکی (PySide6) تبدیل ویدیو برای هد‌یونیت خودرو

طرز استفاده:
    python car_convert_qt.py

نیازمندی:
    pip install PySide6

موتور تبدیل همان car_convert.py است — این فایل فقط پوسته‌ی گرافیکی روی
آن است. هر دو فایل باید کنار هم باشند.

چرا Qt و نه tkinter: Qt متن فارسی را درست می‌چیند (حروف به هم می‌چسبند و
جهت راست‌به‌چپ رعایت می‌شود). در tkinter روی لینوکس این کار انجام نمی‌شود
و متن فارسی ناخوانا می‌شد.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QThread, Signal, QUrl
    from PySide6.QtGui import QDesktopServices, QFont
    from PySide6.QtWidgets import (
        QApplication, QButtonGroup, QFileDialog, QFrame, QGroupBox,
        QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
        QProgressBar, QPushButton, QRadioButton, QTextEdit, QVBoxLayout,
        QWidget,
    )
except ImportError:
    sys.stderr.write(
        "PySide6 نصب نیست.\n\n"
        "    pip install PySide6\n\n"
        "یا از نسخه‌ی tkinter استفاده کنید: python car_convert_gui.py\n"
    )
    sys.exit(2)

try:
    import car_convert as engine
except ImportError:
    sys.stderr.write(
        "فایل car_convert.py پیدا نشد.\n"
        "این دو فایل باید کنار هم باشند:\n"
        "    car_convert.py\n"
        "    car_convert_qt.py\n"
    )
    sys.exit(2)


# --------------------------------------------------------------------------
# رزولوشن‌های پیشنهادی — از بزرگ به کوچک.
#
# کاربر از بالا شروع می‌کند؛ اگر دستگاه ارور داد یکی پایین‌تر را می‌زند.
# همه مضرب ۱۶ هستند چون دیکودرهای MPEG-4 ASP به هم‌ترازی ماکروبلاک
# نیاز دارند.
# --------------------------------------------------------------------------

PRESETS: list[tuple[int, int, str]] = [
    (640, 480, "بزرگ‌ترین تصویر — اول این را امتحان کنید"),
    (640, 360, "عریض‌تر، کمی کوچک‌تر"),
    (480, 360, "برای دستگاه‌های سخت‌گیرتر"),
    (320, 240, "آخرین راه — تقریباً همه‌جا پخش می‌شود"),
]


def format_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB"):
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


class ConvertWorker(QThread):
    """تبدیل در نخ جدا انجام می‌شود تا پنجره قفل نشود."""

    progressed = Signal(int, str)       # شماره‌ی فایل، متن وضعیت
    logged = Signal(str, str)           # متن، نوع ("ok" / "fail" / "info")
    finished_all = Signal(dict)

    def __init__(self, files: list[Path], out_dir: Path,
                 width: int, height: int, ffmpeg: str, ffprobe: str) -> None:
        super().__init__()
        self.files = files
        self.out_dir = out_dir
        self.width = width
        self.height = height
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        done = failed = skipped = 0
        used: set[str] = set()
        started = time.time()

        for index, src in enumerate(self.files, 1):
            if self._cancel:
                self.logged.emit("لغو شد.", "info")
                break

            dst = engine.unique_target(
                self.out_dir, engine.safe_stem(src.stem, index), used)
            self.progressed.emit(index - 1, f"({index} از {len(self.files)})  {src.name}")

            if dst.exists() and dst.stat().st_size > 0:
                self.logged.emit(f"{src.name} — از قبل ساخته شده، رد شد", "info")
                skipped += 1
                self.progressed.emit(index, "")
                continue

            duration = engine.probe_duration(self.ffprobe, src)
            audio = engine.has_audio(self.ffprobe, src)
            crop = None
            if engine.CROP_DETECT:
                crop = engine.detect_crop(
                    self.ffmpeg, src, duration,
                    engine.probe_size(self.ffprobe, src))

            tmp = dst.with_name(dst.name + ".part")
            file_started = time.time()
            result = engine.run(engine.build_command(
                self.ffmpeg, src, tmp, audio, crop,
                size=(self.width, self.height)))

            if self._cancel:
                tmp.unlink(missing_ok=True)
                self.logged.emit("لغو شد.", "info")
                break

            if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                tmp.unlink(missing_ok=True)
                detail = (result.stderr or "").strip().splitlines()
                reason = detail[-1] if detail else "خطای نامشخص"
                self.logged.emit(f"{src.name} — ناموفق: {reason}", "fail")
                failed += 1
                self.progressed.emit(index, "")
                continue

            out_duration = engine.probe_duration(self.ffprobe, tmp)
            if duration > 0 and out_duration > 0 and out_duration < duration * 0.95:
                tmp.unlink(missing_ok=True)
                self.logged.emit(f"{src.name} — خروجی ناقص بود", "fail")
                failed += 1
                self.progressed.emit(index, "")
                continue

            tmp.replace(dst)
            note = "  ·  نوار سیاه حذف شد" if crop else ""
            self.logged.emit(
                f"{dst.name}  ·  {format_size(dst.stat().st_size)}  ·  "
                f"{engine.human_time(time.time() - file_started)}{note}", "ok")
            done += 1
            self.progressed.emit(index, "")

        self.finished_all.emit({
            "done": done, "failed": failed, "skipped": skipped,
            "elapsed": time.time() - started, "cancelled": self._cancel,
        })


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.files: list[Path] = []
        self.out_dir: Path | None = None
        self.worker: ConvertWorker | None = None

        self.setWindowTitle("تبدیل ویدیو برای خودرو")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 700)
        self.setMinimumSize(680, 620)

        self._build()
        self._check_ffmpeg()

    # ------------------------------------------------------------------ ساخت

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        # ---- مرحله ۱
        box1 = QGroupBox("۱ — فیلم‌ها را انتخاب کنید")
        v1 = QVBoxLayout(box1)

        row = QHBoxLayout()
        self.btn_add = QPushButton("افزودن فیلم…")
        self.btn_folder = QPushButton("افزودن یک پوشه…")
        self.btn_remove = QPushButton("حذف انتخاب‌شده")
        self.btn_clear = QPushButton("پاک کردن همه")
        self.btn_add.clicked.connect(self.add_files)
        self.btn_folder.clicked.connect(self.add_folder)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_files)
        for b in (self.btn_add, self.btn_folder, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch(1)
        v1.addLayout(row)

        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QListWidget.ExtendedSelection)
        # اسم فایل‌ها معمولاً انگلیسی است؛ چپ‌چین بهتر خوانده می‌شود.
        self.listbox.setLayoutDirection(Qt.LeftToRight)
        self.listbox.itemSelectionChanged.connect(self._sync_buttons)
        v1.addWidget(self.listbox, 1)

        self.count_label = QLabel("هنوز فیلمی انتخاب نشده.")
        self.count_label.setStyleSheet("color:#555;")
        v1.addWidget(self.count_label)
        outer.addWidget(box1, 1)

        # ---- مرحله ۲
        box2 = QGroupBox("۲ — اندازه‌ی تصویر را انتخاب کنید")
        v2 = QVBoxLayout(box2)
        self.preset_group = QButtonGroup(self)

        for index, (w, h, hint) in enumerate(PRESETS):
            # U+202A (LTR embedding) + U+202C: بدون این، چیدمان راست‌به‌چپ
            # ترتیب اعداد را برعکس نشان می‌دهد — «۴۸۰ × ۶۴۰» به‌جای «۶۴۰ × ۴۸۰».
            rb = QRadioButton(f"\u202a{w} × {h}\u202c")
            rb.setLayoutDirection(Qt.RightToLeft)
            if index == 0:
                rb.setChecked(True)
                font = rb.font()
                font.setBold(True)
                rb.setFont(font)
            self.preset_group.addButton(rb, index)

            line = QHBoxLayout()
            line.addWidget(rb)
            note = QLabel(hint)
            note.setStyleSheet("color:#666;")
            line.addWidget(note)
            line.addStretch(1)
            v2.addLayout(line)

        tip = QLabel(
            "اگر دستگاه فیلم را پخش نکرد یا پیام خطا داد، "
            "یکی پایین‌تر را انتخاب کنید و دوباره بسازید. "
            "هر اندازه در پوشه‌ی جداگانه‌ی خودش ساخته می‌شود، "
            "پس نتیجه‌ی قبلی پاک نمی‌شود."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            "color:#444; background:#f0f4f8; border:1px solid #d8e0e8;"
            "border-radius:6px; padding:8px;")
        v2.addWidget(tip)
        outer.addWidget(box2)

        # ---- مرحله ۳
        row3 = QHBoxLayout()
        self.btn_start = QPushButton("۳ — شروع تبدیل")
        self.btn_start.setMinimumHeight(42)
        start_font = self.btn_start.font()
        start_font.setPointSize(start_font.pointSize() + 2)
        start_font.setBold(True)
        self.btn_start.setFont(start_font)
        self.btn_start.clicked.connect(self.start)

        self.btn_cancel = QPushButton("لغو")
        self.btn_cancel.setMinimumHeight(42)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)

        self.btn_open = QPushButton("باز کردن پوشه‌ی خروجی")
        self.btn_open.setMinimumHeight(42)
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_output)

        row3.addWidget(self.btn_start, 2)
        row3.addWidget(self.btn_cancel, 1)
        row3.addStretch(1)
        row3.addWidget(self.btn_open, 1)
        outer.addLayout(row3)

        # ---- وضعیت
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        outer.addWidget(self.progress)

        self.status = QLabel("آماده.")
        outer.addWidget(self.status)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setLayoutDirection(Qt.LeftToRight)
        self.log_box.setFixedHeight(150)
        self.log_box.setStyleSheet(
            "background:#fbfbfb; border:1px solid #ddd; border-radius:6px;")
        outer.addWidget(self.log_box)

        self._sync_buttons()

    # ------------------------------------------------------------------ ffmpeg

    def _check_ffmpeg(self) -> None:
        self.ffmpeg = engine.find_tool("ffmpeg")
        self.ffprobe = engine.find_tool("ffprobe")
        if self.ffmpeg and self.ffprobe:
            return

        self.btn_start.setEnabled(False)
        self.log("ffmpeg پیدا نشد — بدون آن تبدیل ممکن نیست.", "fail")
        QMessageBox.critical(
            self, "ffmpeg نصب نیست",
            "برنامه برای تبدیل به ffmpeg نیاز دارد و پیدایش نکرد.\n\n"
            "ویندوز:\n"
            "در Command Prompt بزنید:\n"
            "winget install Gyan.FFmpeg\n"
            "بعد این برنامه را ببندید و دوباره باز کنید.\n\n"
            "لینوکس:\n"
            "sudo apt install ffmpeg\n\n"
            "یا پوشه‌ی bin مربوط به ffmpeg را کنار همین برنامه کپی کنید.")

    # ------------------------------------------------------------------ فایل‌ها

    def add_files(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(engine.VIDEO_EXTS))
        chosen, _ = QFileDialog.getOpenFileNames(
            self, "فیلم‌ها را انتخاب کنید", "",
            f"فایل‌های ویدیویی ({patterns});;همه‌ی فایل‌ها (*)")
        self._add([Path(c) for c in chosen])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "پوشه‌ی فیلم‌ها را انتخاب کنید")
        if not folder:
            return
        found = engine.collect_files(Path(folder))
        if not found:
            QMessageBox.information(self, "خالی",
                                    "در این پوشه فایل ویدیویی پیدا نشد.")
            return
        self._add(found)

    def _add(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            if path.suffix.lower() not in engine.VIDEO_EXTS or path in self.files:
                continue
            self.files.append(path)
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            self.listbox.addItem(item)
            added += 1
        if added:
            self.log(f"{added} فایل اضافه شد.", "info")
        self._sync_buttons()

    def remove_selected(self) -> None:
        for item in sorted(self.listbox.selectedIndexes(),
                           key=lambda i: i.row(), reverse=True):
            row = item.row()
            self.listbox.takeItem(row)
            del self.files[row]
        self._sync_buttons()

    def clear_files(self) -> None:
        self.listbox.clear()
        self.files.clear()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        busy = self.worker is not None and self.worker.isRunning()
        count = len(self.files)

        if count:
            total = sum(f.stat().st_size for f in self.files if f.exists())
            self.count_label.setText(
                f"{count} فیلم انتخاب شده  ·  مجموع {format_size(total)}")
        else:
            self.count_label.setText("هنوز فیلمی انتخاب نشده.")

        has_ffmpeg = bool(getattr(self, "ffmpeg", None))
        self.btn_start.setEnabled(bool(count) and not busy and has_ffmpeg)
        self.btn_clear.setEnabled(bool(count) and not busy)
        self.btn_add.setEnabled(not busy)
        self.btn_folder.setEnabled(not busy)
        self.btn_remove.setEnabled(
            bool(self.listbox.selectedIndexes()) and not busy)

    # ------------------------------------------------------------------ اجرا

    def start(self) -> None:
        if not self.files:
            return

        width, height, _hint = PRESETS[self.preset_group.checkedId()]

        # خروجی کنار اولین فیلم، در پوشه‌ای به نام همان اندازه — تا امتحان
        # کردن اندازه‌ی بعدی، نتیجه‌ی قبلی را پاک نکند.
        out_dir = self.files[0].parent / f"{engine.OUTPUT_DIRNAME}_{width}x{height}"
        try:
            out_dir.mkdir(exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "ساخت پوشه ممکن نشد", str(exc))
            return
        self.out_dir = out_dir

        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self.btn_cancel.setEnabled(True)
        self.btn_open.setEnabled(True)

        self.log("", "info")
        self.log(f"شروع — \u202a{width}×{height}\u202c — {len(self.files)} فایل",
                 "info")
        self.log(f"خروجی: {out_dir}", "info")

        self.worker = ConvertWorker(list(self.files), out_dir, width, height,
                                    self.ffmpeg, self.ffprobe)
        self.worker.progressed.connect(self._on_progress)
        self.worker.logged.connect(self.log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()
        self._sync_buttons()

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.status.setText("در حال لغو… صبر کنید تا فایل فعلی تمام شود.")

    def _on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        if text:
            self.status.setText(text)

    def _on_finished(self, stats: dict) -> None:
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        self._sync_buttons()

        summary = (f"موفق: {stats['done']}   ·   "
                   f"رد شده: {stats['skipped']}   ·   "
                   f"ناموفق: {stats['failed']}   ·   "
                   f"زمان: {engine.human_time(stats['elapsed'])}")
        self.status.setText(summary)
        self.log("─" * 46, "info")
        self.log(summary, "info")

        if stats["cancelled"]:
            return

        if stats["done"] or stats["skipped"]:
            QMessageBox.information(
                self, "تمام شد",
                f"{stats['done']} فیلم ساخته شد.\n\n"
                f"پوشه‌ی خروجی:\n{self.out_dir}\n\n"
                "محتویات این پوشه را روی فلش کپی کنید.\n"
                "قبل از کشیدن فلش، حتماً eject بزنید.")
        elif stats["failed"]:
            QMessageBox.warning(
                self, "ناموفق",
                "هیچ فیلمی ساخته نشد. جزئیات خطا در پایین پنجره است.")

    # ------------------------------------------------------------------ کمکی

    def log(self, message: str, kind: str = "info") -> None:
        colour = {"ok": "#1a7f37", "fail": "#c1121f"}.get(kind, "#333")
        prefix = {"ok": "✓ ", "fail": "✗ "}.get(kind, "")
        safe = (message.replace("&", "&amp;")
                       .replace("<", "&lt;").replace(">", "&gt;"))
        self.log_box.append(
            f'<span style="color:{colour};">{prefix}{safe}</span>')
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum())

    def open_output(self) -> None:
        if self.out_dir and self.out_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self, "هنوز تمام نشده",
                "تبدیل در حال انجام است. واقعاً ببندم؟")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
