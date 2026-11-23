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
dm = browser.DeviceManager("devices.txt")
assert len(dm.devices) >= 80, f"devices.txt should load all valid devices, got {len(dm.devices)}"
import info as _info
assert "game_version" in inspect.getsource(_info.GameConnection), "Dynamic game_version capture missing"

# 6. Ephemeral CloakBrowser license activate/withdraw per run
with tempfile.TemporaryDirectory() as tmpd:
    old_cdir = os.environ.get("CLOAKBROWSER_CACHE_DIR")
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
_ep = _info.extract_player_data({0: [{0: 1, 1: 1, 2: "X", 3: 10, 83: 5, 50: 9999999999}]}, {24: "motto_not_int", 22: 200, 77: 100}, 0)
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
assert "stale_browser=browser" in src_worker, "run_worker relaunches must pass stale_browser"
with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
    tf.write("a:1\na:1\nb:2\n")
    _tfp = tf.name
try:
    assert browser.load_combos(_tfp) == [("a", "1"), ("b", "2")], "load_combos must deduplicate pairs"
finally:
    os.remove(_tfp)
print("All hybrid browser stability, 2-tab, cache, license & lookup checks passed.")
