#!/usr/bin/env bash
# fix_python314_ssl.sh — بازسازی پایتون ۳.۱۴ با پشتیبانی SSL
#
# مشکل: پایتون ۳.۱۴ که از سورس کامپایل شده، ماژول _ssl را ندارد، چون
# موقع build کتابخانه‌ی libssl-dev نصب نبوده و configure بی‌سروصدا از
# آن رد شده. نتیجه: pip به هیچ آدرس https وصل نمی‌شود.
#
# این اسکریپت هدرهای OpenSSL را نصب می‌کند و پایتون را دوباره می‌سازد.
#
# اجرا:
#     bash fix_python314_ssl.sh
#
# حدود ۱۰ تا ۲۵ دقیقه طول می‌کشد (به خاطر --enable-optimizations).

set -euo pipefail

VERSION="3.14.4"
BUILD_DIR="${HOME}/src"

echo "──────────────────────────────────────────────────────"
echo "  بازسازی Python ${VERSION} با پشتیبانی SSL"
echo "──────────────────────────────────────────────────────"
echo

# ---------------------------------------------------------------- ۱) هدرها
echo "[۱/۵] نصب کتابخانه‌های لازم…"
sudo apt update
sudo apt install -y \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libffi-dev \
    liblzma-dev \
    libncursesw5-dev \
    tk-dev \
    uuid-dev \
    wget

# libssl-dev همان چیزی است که نبودنش باعث این مشکل شد. بقیه هم برای
# اینکه ماژول‌های دیگر (sqlite3, lzma, tkinter…) هم ساخته شوند.

# ---------------------------------------------------------------- ۲) سورس
echo
echo "[۲/۵] دانلود سورس…"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

if [ ! -f "Python-${VERSION}.tgz" ]; then
    wget "https://www.python.org/ftp/python/${VERSION}/Python-${VERSION}.tgz"
fi
rm -rf "Python-${VERSION}"
tar xzf "Python-${VERSION}.tgz"
cd "Python-${VERSION}"

# ---------------------------------------------------------------- ۳) configure
echo
echo "[۳/۵] پیکربندی…"
./configure \
    --enable-optimizations \
    --with-openssl=/usr \
    --enable-shared \
    --with-ensurepip=install \
    LDFLAGS="-Wl,-rpath,/usr/local/lib"

# --with-openssl=/usr صریحاً می‌گوید OpenSSL کجاست — همان چیزی که دفعه‌ی
# قبل گفته نشده بود.

# ---------------------------------------------------------------- ۴) build
echo
echo "[۴/۵] کامپایل… (طولانی‌ترین مرحله)"
make -j "$(nproc)"

echo
echo "      نصب…"
# altinstall نه install — تا /usr/bin/python3 سیستم دست‌نخورده بماند.
sudo make altinstall
sudo ldconfig

# ---------------------------------------------------------------- ۵) تست
echo
echo "[۵/۵] بررسی نتیجه…"
echo

if /usr/local/bin/python3.14 -c "import ssl; print('   ✓ ssl کار می‌کند:', ssl.OPENSSL_VERSION)"; then
    echo
    echo "──────────────────────────────────────────────────────"
    echo "  تمام شد."
    echo "──────────────────────────────────────────────────────"
    echo
    echo "  حالا می‌توانید:"
    echo
    echo "      cd /home/poolina/Downloads/car-video-convert-main"
    echo "      python3.14 -m venv .venv"
    echo "      source .venv/bin/activate"
    echo "      pip install PySide6"
    echo "      python car_convert_qt.py"
    echo
else
    echo
    echo "   ✗ هنوز ssl کار نمی‌کند."
    echo "     خروجی configure را ببینید؛ معمولاً یعنی libssl-dev"
    echo "     درست نصب نشده یا در مسیر دیگری است."
    exit 1
fi
