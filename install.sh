#!/usr/bin/env bash
set -euo pipefail

# MLBB Fast Checker v9.0 — First-time Setup (Linux / macOS / Termux proot-distro Ubuntu-Debian)
cd "$(dirname "${BASH_SOURCE[0]}")"

KEY_DEFAULT="cb_3c59a9fa1a2841aeab3194b483542320"
LIC_KEY="${1:-${CLOAKBROWSER_LICENSE_KEY:-$KEY_DEFAULT}}"

echo "[*] MLBB Fast Checker — First-time Installer"

# Detect raw Android Termux (bionic libc cannot execute linux-arm64 glibc Chromium binaries)
if [ -n "${TERMUX_VERSION:-}" ] && [ ! -f /etc/os-release ]; then
    echo "[!] Termux native (bionic) terdeteksi."
    echo "    CloakBrowser butuh glibc (linux-arm64). Jalankan lewat Ubuntu proot-distro:"
    echo "      pkg update && pkg install -y proot-distro"
    echo "      proot-distro install ubuntu && proot-distro login ubuntu"
    echo "    Lalu jalankan kembali: bash install.sh"
    exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

# 1. System base packages (Python3 + venv + pip)
if command -v apt-get >/dev/null 2>&1; then
    echo "[*] Memasang paket dasar apt (python3, venv, pip, curl)..."
    $SUDO apt-get update -y
    $SUDO apt-get install -y python3 python3-venv python3-pip curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y python3 python3-pip curl ca-certificates
elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm python python-pip curl ca-certificates
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 tidak ditemukan. Pasang Python 3.10+ terlebih dahulu."
    exit 1
fi

# 2. Virtualenv (.venv) agar aman terhadap PEP 668 di Ubuntu/Debian modern
if [ ! -d ".venv" ]; then
    echo "[*] Membuat virtualenv .venv..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[*] Upgrade pip & memasang dependensi Python..."
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade cloakbrowser playwright pycryptodome zstandard curl_cffi colorama

# 3. Dependensi library OS untuk Chromium/CloakBrowser (Linux)
if [ "$(uname -s)" = "Linux" ]; then
    echo "[*] Memasang library sistem Chromium (playwright install-deps)..."
    if ! python -m playwright install-deps chromium; then
        $SUDO env "PATH=$PATH" python -m playwright install-deps chromium || true
    fi
fi

# 4. Unduh binary CloakBrowser Pro memakai key sementara, lalu tarik kembali key dari disk
echo "[*] Mengunduh binary CloakBrowser Pro..."
CLOAKBROWSER_LICENSE_KEY="$LIC_KEY" python -m cloakbrowser install

# Tarik file license/cache agar aman pindah device (key kembali disuntik otomatis tiap run)
CACHE_DIR="${CLOAKBROWSER_CACHE_DIR:-$HOME/.cloakbrowser}"
rm -f "$CACHE_DIR/license.key" "$CACHE_DIR/.license_cache" "$CACHE_DIR/.license_cache.tmp" "$CACHE_DIR/.free_claim" 2>/dev/null || true
unset CLOAKBROWSER_LICENSE_KEY

# 5. Verifikasi cepat
echo "[*] Menjalankan verifikasi..."
python browser.py --selftest
python test_browser_check.py

echo ""
echo "[✓] Instalasi selesai! Jalankan dengan:"
echo "    source .venv/bin/activate && python browser.py"
