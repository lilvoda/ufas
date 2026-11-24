import browser, inspect, os, tempfile

# 1. Classification integrity
assert browser.classify({'code': 1004, 'message': 'Kata sandi salah'}) == 'INVALID'
assert browser.classify({'code': 1087, 'message': 'Auth error'}) == 'INVALID'
assert browser.classify({'code': 1001, 'message': 'Email format error'}) != 'OTP'
assert browser.classify({'code': 1086, 'message': 'Verify code'}) == 'OTP'

# 2. Sticky session persistence & fast region filtering
for i in range(20):
    ru = browser.rotated_user("token__cr.zw", session_id=f"w{i}e0")
    assert ru["region"].lower() in browser.DATAIMPULSE_REGIONS
ru1 = browser.rotated_user("token__cr.id", session_id="w0e0")
ru2 = browser.rotated_user("token__cr.id", session_id="w0e0")
assert ru1["user"] == ru2["user"]

# 3. Direct HTTP POST payload & stability timeout/WAF guards
p = browser.build_login_payload("John375", "John375")
assert p["sign"] == "4505fe2cd2c648dc8d7cb2986109a9d9"
src_login = inspect.getsource(browser.do_login_via_browser)
assert "timeout=12.0" in src_login and "waf_challenge_unsolved" in src_login
assert "sent_acct" in src_login and "new_login_pwd" in src_login, "Missing request/account binding guard in on_resp"

# 4. Anti-cookie-poisoning, RAM static asset cache & 2-tab pipelining
assert hasattr(browser, "_STATIC_CACHE") and hasattr(browser, "_route_filter")
src_worker = inspect.getsource(browser.run_worker)
assert "ctx_opts['storage_state']" not in src_worker and "page2" in src_worker
assert "page2 or page" not in src_worker, "Tab 1 must never alias Tab 0's page"
assert "my_gen != ctx_gen" in src_worker, "Context switch must not burn account retries"
assert "_startup_failed" in src_worker, "Startup failure must trigger restart loop when queue non-empty"
assert "_browser_license_restart" in src_worker, "Browser/license error must trigger relaunch instead of burning err.txt"
src_main = inspect.getsource(browser.async_main)
assert "ensure_browser" in src_main and "is_connected()" in src_main, "Browser crash auto-relaunch missing"
assert "_acquire_instance_lock" in src_main, "Single-instance lock missing"

# 5. info.py + devices.txt lookup active
assert browser.INFO_OK is True, f"info.py import failed: {browser.INFO_IMPORT_ERR}"
dm = browser.DeviceManager(os.path.join(os.path.dirname(os.path.abspath(__file__)), "devices.txt"))
assert len(dm.devices) >= 80, f"devices.txt should load all valid devices, got {len(dm.devices)}"
import info as _info
import full_info as _full_info
assert "game_version" in inspect.getsource(_info.GameConnection), "Dynamic game_version capture missing"

# 6. Ephemeral CloakBrowser license activate/withdraw per run
with tempfile.TemporaryDirectory() as tmpd:
    old_cdir = os.environ.get("CLOAKBROWSER_CACHE_DIR")
    old_lkey = os.environ.get("CLOAKBROWSER_LICENSE_KEY")
    old_cfg = browser._CONFIGURED_LICENSE_KEY
    old_act = browser._ACTIVE_LICENSE_KEY
    old_sess = browser._LICENSE_SESSION_ACTIVE
    os.environ["CLOAKBROWSER_CACHE_DIR"] = tmpd
    try:
        for fn in ("license.key", ".license_cache", ".free_claim"):
            open(os.path.join(tmpd, fn), "w").write("dummy")
        k = browser.activate_cloak_license()
        assert k.startswith("cb_") and os.environ.get("CLOAKBROWSER_LICENSE_KEY") == k
        browser.withdraw_cloak_license()
        assert "CLOAKBROWSER_LICENSE_KEY" not in os.environ
        assert browser._ACTIVE_LICENSE_KEY == "" and not browser._LICENSE_SESSION_ACTIVE
        for fn in ("license.key", ".license_cache", ".free_claim"):
            assert not os.path.exists(os.path.join(tmpd, fn))
    finally:
        if old_cdir is None:
            os.environ.pop("CLOAKBROWSER_CACHE_DIR", None)
        else:
            os.environ["CLOAKBROWSER_CACHE_DIR"] = old_cdir
        if old_lkey is None:
            os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
        else:
            os.environ["CLOAKBROWSER_LICENSE_KEY"] = old_lkey
        browser._CONFIGURED_LICENSE_KEY = old_cfg
        browser._ACTIVE_LICENSE_KEY = old_act
        browser._LICENSE_SESSION_ACTIVE = old_sess

src_launch = inspect.getsource(browser.launch_browser_smart)
assert "license_key=" in src_launch

# 7. Audited bug regression checks (TUI _LIVE_LOGS str-only, empty proxy abort, WAF JSON guard, info.py fixes)
browser._LIVE_LOGS.clear()
browser.print_result("ERR", "worker-0", "sys", "restart #1")
assert all(isinstance(x, str) for x in browser._LIVE_LOGS), "_LIVE_LOGS must contain strings only"
assert "_LIVE_LOGS.append((" not in src_main, "worker_with_restart must not append raw tuples to _LIVE_LOGS"
assert "if not raw_p:" in src_main, "Missing empty proxy file abort guard"
assert "not body.startswith(\"{\")" in inspect.getsource(browser.do_fast_http_post)
assert "extract_player_data(role_detail, role_info, 0)" in inspect.getsource(_info.get_player_info)
assert "size < 4" in inspect.getsource(_info.BaseConnection.recv_data)
_ep_lean = _info.extract_player_data({0: [{0: 12345, 1: 2020, 2: "X", 3: 10, 8: 112, 95: 140, 83: 45}]})
assert _ep_lean and _ep_lean["data"]["basic_info"]["player_id"] == 12345 and _ep_lean["data"]["basic_info"]["skin_count"] == 45
assert _ep_lean["data"]["game_info"]["current_rank"] == "Legend V" and "extra_info" not in _ep_lean["data"], "info.py must stay lean (ID, skin, rank only)"
_ep = _full_info.extract_player_data({0: [{0: 1, 1: 1, 2: "X", 3: 10, 83: 5, 50: 9999999999}]}, {24: "motto_not_int", 22: 200, 77: 100}, 0)
assert _ep and _ep["data"]["extra_info"]["likes"] == 0
assert _ep["data"]["extra_info"]["win_rate"] == "N/A"
assert _ep["data"]["extra_info"]["starlight_user"] == "No"

# 8. Universal terminal UI adaptation (wide, narrow, short, CJK clip, ANSI/ASCII fallback)
import io, os as _os, shutil as _shutil, sys as _sys
_old_tui, _old_out, _old_gts = browser._TUI_ACTIVE, _sys.stdout, _shutil.get_terminal_size
try:
    browser._TUI_ACTIVE = True
    browser.stats.update({'total': 1000, 'checked': 42, 'valid': 1, 'start': 1.0, 'workers': 4, 'workers_total': 5, 'proxy_label': 'very_long_proxy_file_name_12345.txt'})
    browser._TOP_HITS[:] = ["verylongaccountname123:verylongpassword123 | Lv69 | 124 Skins | Mythical Immortal 150"]
    for st_name in ("RUNNING", "REFRESH", "WAF_WAIT", "DONE"):
        browser.stats['status'] = st_name
        for cols, rows in ((120, 40), (80, 24), (50, 18), (42, 12)):
            buf = io.StringIO()
            _sys.stdout = buf
            _shutil.get_terminal_size = lambda fallback=(80, 24), _c=cols, _r=rows: _os.terminal_size((_c, _r))
            browser.render_dashboard(force=True)
            frame = buf.getvalue().replace("\033[H", "").replace("\033[J", "")
            lines = [ln.replace("\033[K", "") for ln in frame.split("\n")]
            assert len(lines) <= rows, f"Frame height {len(lines)} > {rows} at {cols}x{rows} ({st_name})"
            assert all(browser._vis_len(ln) <= cols for ln in lines), f"Line overflow at {cols}x{rows} ({st_name})"
    browser.stats['status'] = 'RUNNING'
finally:
    browser._TUI_ACTIVE, _sys.stdout, _shutil.get_terminal_size = _old_tui, _old_out, _old_gts
    browser._TOP_HITS.clear()

assert "tab0_done" in src_worker, "Tab 1 end-of-queue deadlock guard missing"
assert "PROXY_HTTP_ERR" in src_login, "Fast proxy HTTP error wake missing"
assert "browser_state" in src_main and "zero_evt" in src_main, "Periodic Chromium recycle gate missing"
assert "timeout=8" in inspect.getsource(browser.send_tg), "send_tg urlopen timeout missing"
assert "fail_count >= 6" in src_main, "Cascade restart threshold should be >= 6"
assert "accountmtapi.mobilelegends.com" in inspect.getsource(browser._probe_proxy_ms), "API latency probe missing"
assert "cutoff_ms" in inspect.getsource(browser.test_proxies), "Abnormal latency cutoff missing"
assert "stale_browser" in src_main and "last_relaunch" in src_main, "Thundering-herd relaunch guard missing"
assert "browser_state['active'] == 0" in src_worker and "acct_retries" in src_worker, "Safe recycle / persistent retry guard missing"
assert "reason == 'periodic_rotate' and inflight_tabs" not in src_worker, "_recover_ctx must wait for inflight_tabs on all recovery types"
_bc = _info.BaseConnection("127.0.0.1", 30021)
_bc.queue_data = b"leftover"
_bc.cleanup()
assert _bc.queue_data == b"", "BaseConnection.cleanup must clear queue_data"
# Truncated STRUCT_BEGIN and truncated varint must terminate cleanly without infinite loop
_trunc = _info.SdpStruct(bytes([(_info.SdpDataType.STRUCT_BEGIN.value << 4), (_info.SdpDataType.STRUCT_BEGIN.value << 4) | 1]))
assert isinstance(_trunc, dict)
try:
    _info.SdpStruct(bytes([(_info.SdpDataType.STRUCT_BEGIN.value << 4), 0x0F, 0x80]))
    assert False, "Truncated varint should raise SdpException"
except _info.SdpException:
    pass
# Multi-agent audit regression assertions
assert "'err_' not in err_low and 'net::' not in err_low" in src_worker, "Proxy net::ERR_ errors must never relaunch shared browser"
assert "code >= 500" in inspect.getsource(browser._probe_proxy_ms), "5xx gateway errors must be rejected in proxy probe"
assert "except Exception:" not in inspect.getsource(browser._touch), "_touch must not swallow CDP errors from _human_drag"
assert browser.parse_proxy("http://u__cr.sg,my:p@gw.dataimpulse.com:823")["username"] == "u__cr.sg,my", "Multi-country comma in proxy username must be preserved"
_dm1 = _info.DeviceManager("__nonexistent_devices__.txt")
assert _dm1.get_next_device(_dm1.devices[0]) == _dm1.devices[0], "1-device fallback pool must not return None on retry"
assert _info.extract_player_data({1: "no_zero_key"}) is None, "extract_player_data missing key 0 must not raise KeyError"
assert "os.path.join(BASE, 'output', _stem)" in src_main, "Per-input resume OUTPUT_DIR missing"
assert browser.WAVE_REFRESH_EVERY == 1000 and "wave_limit" in src_main and "wave_limit" in src_worker, "1k wave worker refresh missing"
assert "_STATIC_CACHE.clear()" not in src_main and "_TUNNEL_BLACKLIST.clear()" not in src_main, "1k refresh must keep RAM JS cache & tunnel blacklist"
assert "stale_browser=" in src_worker, "run_worker relaunches must pass stale_browser"
assert "_kill_driver_tree" in src_main, "ensure_browser must kill PID tree without withdrawing Cloak license mid-run"
assert "aborted_on_errors" in src_main and "checked_before" in src_main, "1k wave refresh must detect stall/abort cleanly"
assert browser.parse_proxy("user:123456:1.2.3.4:8080") == {"server": "http://1.2.3.4:8080", "username": "user", "password": "123456"}
assert browser.rotated_user("tok__cr.id,th", session_id="w0e0")["region"] in ("ID", "TH"), "Explicit __cr. regions must be honored with session_id"
assert "proxy_407" in src_login and "Client_InvalidPasswordRule" in src_login, "Fast 407 & client password validation must be active"
assert "isinstance(res, str)" in inspect.getsource(_info.BaseConnection.recv_data), "recv_data must accept UTF-8-decoded binary payloads"
with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
    tf.write("Alice:Pass1\nalice:Pass1\nalice:pass1\nb:2\n")
    _tfp = tf.name
try:
    assert browser.load_combos(_tfp) == [("Alice", "Pass1"), ("alice", "pass1"), ("b", "2")], "load_combos must keep password case-sensitivity"
finally:
    os.remove(_tfp)

# 9. Behavioral 1k wave refresh + HTTP 502/407 + fast Client_InvalidPasswordRule tests
import asyncio as _asyncio, sys as _sys_t

async def _run_behavioral_checks():
    # A. do_login_via_browser: 502 HTML -> PROXY_HTTP_ERR (not WAF), 407 -> proxy_407, client validation -> INVALID
    class _FakeResp:
        def __init__(self, status, url="https://accountmtapi.mobilelegends.com/", method="POST", post_data='{"op":"new_login_pwd","params":{"account":"a1"}}'):
            self.status = status
            self.url = url
            class _Req:
                pass
            self.request = _Req()
            self.request.method = method
            self.request.post_data = post_data

        async def text(self):
            return "<html><body>502 Bad Gateway</body></html>"

    class _FakePage:
        def __init__(self, mode):
            self.mode = mode
            self.url = browser.LOGIN_PAGE
            self._ls = {}

        def on(self, ev, fn):
            self._ls.setdefault(ev, []).append(fn)

        def remove_listener(self, ev, fn):
            if ev in self._ls and fn in self._ls[ev]:
                self._ls[ev].remove(fn)

        async def evaluate(self, js, arg=None):
            if "formComp.submit" in js:
                if self.mode in ("502", "407"):
                    for fn in list(self._ls.get("response", [])):
                        r = fn(_FakeResp(int(self.mode)))
                        if _asyncio.iscoroutine(r):
                            await r
                return "OK"
            if "errEl" in js:
                return self.mode == "client_invalid"
            return False

    k502, d502 = await browser.do_login_via_browser(_FakePage("502"), None, "a1", "pw1")
    assert k502 == "ERR" and d502.get("message") == "PROXY_HTTP_ERR", f"502 HTML misclassified: {k502} {d502}"
    k407, d407 = await browser.do_login_via_browser(_FakePage("407"), None, "a1", "pw1")
    assert k407 == "ERR" and d407.get("proxy_407") is True, f"407 not flagged: {k407} {d407}"
    kci, dci = await browser.do_login_via_browser(_FakePage("client_invalid"), None, "a1", "bad")
    assert kci == "INVALID" and dci.get("message") == "Client_InvalidPasswordRule", f"Expected fast client invalid, got {kci} {dci}"

    # B. Multi-wave restart every WAVE_REFRESH_EVERY accounts (simulated with wave=3 over 7 combos)
    with tempfile.TemporaryDirectory() as td:
        cfp = os.path.join(td, "c7.txt")
        outd = os.path.join(td, "out")
        with open(cfp, "w", encoding="utf-8") as cf:
            for i in range(7):
                cf.write(f"u{i}:p{i}\n")
        orig_vals = (
            browser.WAVE_REFRESH_EVERY,
            browser.launch_browser_smart,
            browser.run_worker,
            browser.withdraw_cloak_license,
            browser.activate_cloak_license,
            browser._acquire_instance_lock,
            browser._release_instance_lock,
            list(_sys_t.argv),
            browser._TUI_ACTIVE,
        )
        launches = []
        closed = []
        withdraws = []
        seen_waves = []

        class _FakeB:
            def __init__(self, idx):
                self.idx = idx
            def is_connected(self):
                return True
            async def close(self):
                closed.append(self.idx)

        async def _fake_launch(headless=True, humanize=False):
            b = _FakeB(len(launches))
            launches.append(b.idx)
            return b

        async def _fake_worker(wid, combos, combo_q, b, dm, p_info, live_pool, ensure_browser=None, browser_state=None, acct_retries=None, wave_limit=0, wave_idx=0):
            seen_waves.append((wave_idx, b.idx))
            while not combo_q.empty() and (not wave_limit or browser.stats['checked'] < wave_limit):
                u, p = combo_q.get_nowait()
                browser.stats['checked'] += 1
                browser.stats['invalid'] += 1
                combo_q.task_done()

        try:
            browser.WAVE_REFRESH_EVERY = 3
            browser.launch_browser_smart = _fake_launch
            browser.run_worker = _fake_worker
            browser.activate_cloak_license = lambda k="": "cb_testkey"
            browser.withdraw_cloak_license = lambda: withdraws.append("withdrawn")
            browser._acquire_instance_lock = lambda: None
            browser._release_instance_lock = lambda fh: None
            browser._LICENSE_SESSION_ACTIVE = True
            for k_s in ('valid', 'invalid', 'otp', 'error', 'waf', 'checked', 'proxy_ctx', 'bytes_used'):
                browser.stats[k_s] = 0
            _sys_t.argv = ["browser.py", cfp, "--workers", "1", "--no-proxy", "--no-prompt", "--out", outd]
            await browser.async_main()
            assert browser.stats['checked'] == 7, f"Expected 7 checked across 3 waves, got {browser.stats['checked']}"
            assert launches == [0, 1, 2], f"Expected 3 browser launches (1 + 2 wave refreshes), got {launches}"
            assert seen_waves == [(0, 0), (1, 1), (2, 2)], f"Unexpected wave/browser sequence: {seen_waves}"
            assert len(withdraws) == 1, f"License must only withdraw once at final exit, got {withdraws}"
        finally:
            (
                browser.WAVE_REFRESH_EVERY,
                browser.launch_browser_smart,
                browser.run_worker,
                browser.withdraw_cloak_license,
                browser.activate_cloak_license,
                browser._acquire_instance_lock,
                browser._release_instance_lock,
                _sys_t.argv,
                browser._TUI_ACTIVE,
            ) = orig_vals
            browser._LICENSE_SESSION_ACTIVE = False

_asyncio.run(_run_behavioral_checks())

# 10. Smart speed-drop detector: warmup guard, attribution, cooldown & recovery
_det = browser._SpeedDetector(window_s=30.0)
_det.reset(now_t=0.0)
browser.stats['workers'] = 2
assert not _det.evaluate(now_t=5.0)[0], "Must not false-alarm during warmup"
for i in range(12):
    _det.mark_check(now_t=1.0 + i * 1.0)
assert not _det.evaluate(now_t=13.0)[0], "Steady baseline must not trigger drop"
_det.record_stall('proxy', 12.0, now_t=32.0)
_det.record_stall('waf', 3.0, now_t=33.0)
_is_d, _tag, _desc, _pct, _cr, _pr = _det.evaluate(now_t=34.0)
assert _is_d and _tag == 'PROXY' and _pct == 80, f"Expected PROXY 80% drop, got {(_is_d, _tag, _pct)}"
assert _det.maybe_alert(now_t=34.0) is not None, "First drop transition must emit alert"
assert _det.maybe_alert(now_t=40.0) is None, "Cooldown must suppress repeat alert within 25s"
for j in range(12):
    _det.mark_check(now_t=41.0 + j * 0.5)
assert _det.maybe_alert(now_t=47.0) is None and not _det.was_drop, "Detector must clear after rate recovers"
_det.resume(now_t=62.0)
assert not _det.evaluate(now_t=63.0)[0], "Wave/recycle pause resume() must prevent false idle drop alarm"
assert "PROXY" in _det.summary(), f"Summary missing dominant bottleneck: {_det.summary()}"

# 11. Bandwidth optimization guards (_ROUTE_RE domain blocks & disk static cache round-trip)
for _blk_u in (
    "https://www.google.com/complete/search",
    "https://content-autofill.googleapis.com/v1/pages/abc",
    "https://158.177.38.248/",
    "https://errors.aliyun.com/images/test",
):
    assert browser._ROUTE_RE.search(_blk_u), f"Expected blocked route match for {_blk_u}"
for _ok_u in (
    "https://accountmtapi.mobilelegends.com/",
    "https://cloudauth-device-dualstack.ap-southeast-1.aliyuncs.com/device",
    "https://91b88bfa1d2370355377a8568184628c.captcha-open-southeast.aliyuncs.com/init",
):
    assert not browser._ROUTE_RE.search(_ok_u), f"Must not intercept API route {_ok_u}"

with tempfile.TemporaryDirectory() as _cd:
    _cf = os.path.join(_cd, "cache.bin")
    _saved_cache = dict(browser._STATIC_CACHE)
    browser._STATIC_CACHE.clear()
    try:
        browser._STATIC_CACHE["https://o.alicdn.com/test.js"] = (200, {"content-type": "application/javascript"}, b"console.log(1);")
        browser._save_static_cache(_cf)
        browser._STATIC_CACHE.clear()
        assert browser._load_static_cache(_cf) == 1
        assert browser._STATIC_CACHE["https://o.alicdn.com/test.js"][2] == b"console.log(1);"
    finally:
        browser._STATIC_CACHE.clear()
        browser._STATIC_CACHE.update(_saved_cache)

print("All hybrid browser stability, 2-tab, cache, license & lookup checks passed.")
