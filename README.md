# MLBB Fast Checker v9.0 (`BrowserEngine`)

Browser-based checker & player profile lookup tool powered by CloakBrowser Pro / Playwright with automatic Aliyun WAF slider solving, sticky proxy rotation, ephemeral per-run license handling, and a compact ANSI TUI dashboard.

## Features

- **Hybrid Browser Engine (`browser.py`)**: Direct Vue bridge + fallback DOM typing, automatic Aliyun slider verification (`solve_waf`), and `POST` request/account verification (`params.account`) to prevent cross-account response mixups.
- **2-Tab Pipelining & Auto-Recovery**: Isolated Tab 0 / Tab 1 workers with context synchronization, automatic IP rotation on WAF/rate-limit, and automatic browser relaunch if the browser process disconnects.
- **Quota & Speed Optimizations**: In-memory static `.js`/`.css` caching (`_STATIC_CACHE`), heavy asset blocking (`image`, `media`, `font`), CDP wire-byte quota tracking, and proactive context rotation (`ACCOUNTS_PER_CTX = 30`).
- **Universal Proxy Support**: Supports `HTTP`, `HTTPS`, `SOCKS4/4A`, `SOCKS5/5H` (`scheme://[user:pass@]host:port`, `host:port:user:pass`, `user:pass:host:port`, `user:pass@host:port`, `host:port`), plus DataImpulse sticky country/session rotation.
- **Player Info Lookup (`info.py` + `devices.txt`)**: Automatic player rank/level/skin lookup on valid hits when `info.py` and `devices.txt` are present.
- **Ephemeral License Lifecycle**: Injects the CloakBrowser license key at startup (`--license-key` or `CLOAKBROWSER_LICENSE_KEY`) and closes the browser cleanly while wiping cached license files on exit so seats/keys can move between devices.

## Project Structure

- `browser.py` — Main browser checker, TUI dashboard, WAF slider solver, and proxy manager
- `install.sh` — First-time installer for Linux / macOS / Termux (`proot-distro` Ubuntu/Debian)
- `info.py` & `devices.txt` — Player info lookup module and device profiles
- `test_browser_check.py` — Unit & structural verification tests

## Installation

### Linux / macOS / Termux (`proot-distro` Ubuntu)

```bash
git clone https://github.com/lilvoda/seker.git
cd seker
chmod +x install.sh
./install.sh
```

> **Note for Termux (Android):** Native Termux uses Bionic libc, whereas CloakBrowser Pro binaries require glibc (`linux-arm64`). Run inside Ubuntu via `proot-distro`:
> ```bash
> pkg update && pkg install -y proot-distro
> proot-distro install ubuntu && proot-distro login ubuntu
> ```

### Windows (Manual)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install cloakbrowser playwright pycryptodome zstandard curl_cffi colorama
python -m cloakbrowser install
```

## Usage

### Interactive Mode

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python browser.py
```

### Non-Interactive / CLI Mode

```bash
python browser.py combo.txt --no-prompt --workers 4 --proxy-file proxies.txt --out output
```

### CLI Flags

| Flag | Description |
| --- | --- |
| `combo` | Path to combo file (`user:pass`) |
| `--workers N` | Number of concurrent browser contexts (`1-30`) |
| `--proxy-file PATH` | Path to proxy list file |
| `--no-proxy` | Run without proxies (direct mode) |
| `--out DIR` | Custom output directory (default: `output/`) |
| `--headless` / `--no-headless` | Run headless (default) or visible window |
| `--license-key KEY` | Override CloakBrowser license key for this run |
| `--no-prompt` | Skip interactive prompts |
| `--debug` | Enable debug logging (when TUI is inactive) |
| `--selftest` | Run built-in self-tests |

### Optional Environment Variables

- `CLOAKBROWSER_LICENSE_KEY` — CloakBrowser Pro license key override
- `TG_TOKEN` & `TG_CHAT` — Telegram bot notifications for `VALID` and `2FA / OTP` hits

## Output Files

Results are written to `<OUTPUT_DIR>/` (resumed automatically on subsequent runs for the same output directory):

- `hit_valid.txt` — Valid accounts with session, GUID, name, and timestamp
- `hit_2fa.txt` — Accounts requiring 2FA / OTP verification
- `invalid.txt` — Checked invalid credentials
- `err.txt` — Unresolved errors after retries

## Verification

```bash
python browser.py --selftest
python test_browser_check.py
```
