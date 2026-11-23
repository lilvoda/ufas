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
src_main = inspect.getsource(browser.async_main)
assert "ensure_browser" in src_main and "is_connected()" in src_main, "Browser crash auto-relaunch missing"

# 5. info.py + devices.txt lookup active
assert browser.INFO_OK is True, f"info.py import failed: {browser.INFO_IMPORT_ERR}"
dm = browser.DeviceManager("devices.txt")
assert len(dm.devices) > 0

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
print("All hybrid browser stability, 2-tab, cache, license & lookup checks passed.")
