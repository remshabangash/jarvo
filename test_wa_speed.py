"""Logic tests for the zero-reload WhatsApp flow — NO browser, NO real send.

Fake driver simulates the WhatsApp DOM so we can verify:
  - same-chat fast path fires and skips search
  - stale same-chat cache falls back to search path
  - search path works and header verification passes
  - WRONG header blocks the send (safety) with a clear error
Run:  venv\\Scripts\\python test_wa_speed.py
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import types

import whatsapp_bot


# Prevent the REAL Edge from launching inside logic tests.
class _NoLaunch:
    def __getattr__(self, name):
        raise AssertionError("real browser launch attempted in logic test")


_TEST_DRIVER = {"d": None}
whatsapp_bot.ensure_whatsapp_loaded = lambda timeout=60: _TEST_DRIVER["d"] or _NoLaunch()
whatsapp_bot._driver = _NoLaunch()
whatsapp_bot._alive = lambda d: True


class FakeEl:
    def __init__(self, text=""):
        self._text = text
        self.sent = []

    def is_displayed(self):
        return True

    @property
    def text(self):
        return self._text

    def click(self):
        pass

    def send_keys(self, *a):
        self.sent.append(a)


class FakeDriver:
    def __init__(self, header="Asif"):
        self.header = header
        self.composer = FakeEl("composer")
        self.search = FakeEl("search")
        self.results = [FakeEl(" Asif last seen recently")]
        self.url = "https://web.whatsapp.com/"
        self.navigations = 0
        self.title = "WhatsApp"

    def get(self, url):
        self.navigations += 1
        self.url = url

    def current_url(self):
        return self.url

    def find_element(self, by, sel):
        if "header" in sel:
            el = FakeEl(self.header)
            el.get_attribute = lambda k: self.header if k == "title" else ""
            return el
        if "data-tab=\"3\"" in sel or "Search or start" in sel:
            return self.search
        if "data-tab=\"10\"" in sel or "footer" in sel:
            return self.composer
        raise Exception("no element")

    def find_elements(self, by, sel):
        if "listitem" in sel or "option" in sel:
            return self.results
        return []

    def save_screenshot(self, p):
        pass


def run():
    # Patch state probe to always 'loaded'; verify-stub (real DOM nahi hai)
    whatsapp_bot._wa_state = lambda d: "loaded"
    whatsapp_bot._verify_sent = lambda d, message, timeout=10: True

    # ---- Test 1: same-chat fast path (no search, no navigation) ----
    d = FakeDriver("asif")
    _TEST_DRIVER["d"] = d
    whatsapp_bot._open_chat = {"name": "Asif", "header": "asif"}
    orig_resolve = whatsapp_bot.resolve_contact
    whatsapp_bot.resolve_contact = lambda c: ("Asif", "923001234567")
    try:
        result = whatsapp_bot.send_message("Asif", "hello test")
        assert "sent to Asif" in result, result
        assert d.navigations == 0, f"navigated {d.navigations}x (should be 0)"
        print("T1 PASS: same-chat fast path, 0 navigations")
    finally:
        whatsapp_bot.resolve_contact = orig_resolve
        whatsapp_bot._open_chat = None

    # ---- Test 2: stale cache -> search path still succeeds ----
    # Simulated stale cache: fast-path send returns False once (composer
    # vanished), then the in-app search flow recovers WITHOUT navigation.
    d2 = FakeDriver("Asif")
    _TEST_DRIVER["d"] = d2
    whatsapp_bot._open_chat = {"name": "Asif", "header": "asif"}
    whatsapp_bot.resolve_contact = lambda c: ("Asif", "923001234567")
    orig_type = whatsapp_bot._type_then_send
    calls = {"n": 0}

    def flaky_type(dd, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # fast path hits a stale cache
        return orig_type(dd, msg)

    whatsapp_bot._type_then_send = flaky_type
    try:
        result = whatsapp_bot.send_message("Asif", "hello test")
        assert "sent to Asif" in result, result
        assert d2.navigations == 0, f"navigated {d2.navigations}x (should be 0)"
        assert calls["n"] >= 2, "should have retried via search path"
        print("T2 PASS: stale cache recovered via in-app search, 0 navigations")
    finally:
        whatsapp_bot._type_then_send = orig_type
        whatsapp_bot.resolve_contact = orig_resolve
        whatsapp_bot._open_chat = None

    # ---- Test 3: WRONG header blocks the send ----
    d3 = FakeDriver("Mom")  # opened chat is NOT the contact
    _TEST_DRIVER["d"] = d3
    whatsapp_bot._open_chat = None
    whatsapp_bot.resolve_contact = lambda c: ("Asif", None)

    def no_composer_el(dd, msg):
        raise AssertionError("should never type into wrong chat")

    whatsapp_bot._type_then_send = no_composer_el
    try:
        try:
            whatsapp_bot.send_message("Asif", "secret message")
            raise SystemExit("T3 FAIL: sent into wrong chat!")
        except whatsapp_bot.WaError as e:
            assert "header" in str(e).lower() or "matched" in str(e).lower(), e
            print(f"T3 PASS: wrong-header send blocked -> {str(e)[:60]}...")
    finally:
        whatsapp_bot._type_then_send = orig_type
        whatsapp_bot.resolve_contact = orig_resolve
        whatsapp_bot._open_chat = None

    print("\nALL LOGIC TESTS PASS ✅")


if __name__ == "__main__":
    run()
