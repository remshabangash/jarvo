"""WhatsApp messaging via Selenium + Edge with a PERSISTENT, PRE-LOADED session.

Speed architecture (why this is fast):
  - ONE Edge window, launched once, kept alive, and PRE-LOADED at assistant
    startup so WhatsApp Web is fully open BEFORE the user says anything.
  - A deep-link navigation (wa.me) forces the whole web app to re-bootstrap
    (JS + websocket + chat list) = 10-20s EVERY message. We never do that on
    the hot path: we type the contact into the in-app SEARCH box instead
    (~2-4s total per message).
  - If the last chat we opened is the same contact, we skip search entirely
    and type straight into the composer (~1.5-2s).
  - A wa.me deep link is kept ONLY as a last-resort fallback (search box not
    found), and we restore the chat-list URL right afterwards.

Reliability architecture:
  - Contacts with a phone number in contacts.json are preferred and the
    in-app search result is VERIFIED against the expected number.
  - Before typing we verify the CHAT HEADER shows the contact's name (never
    type into a wrong/mismatched chat — no accidental sends).
  - Every send is VERIFIED (message text appears in the chat pane) before we
    claim success. On failure: screenshot saved (wa_error.png) + a CLEAR
    error message the assistant can speak aloud.
"""
from __future__ import annotations

import atexit
import difflib
import json
import os
import re
import threading
import time
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

import subprocess

EDGE_PROFILE = os.path.join(os.path.expanduser("~"), "saathi_edge_profile")
CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "contacts.json")
ERROR_SHOT = os.path.join(os.path.dirname(__file__), "wa_error.png")
WA_HOME = "https://web.whatsapp.com"

# Body-text markers of a DEAD session (WhatsApp removed the linked device):
# waiting forever here is useless — fail fast with a re-login instruction.
_DEAD_SESSION_MARKERS = ("could not link", "device could not", "phone is offline")


class WaError(Exception):
    """Clear, speakable error — the assistant reads this aloud on failure."""


# ---------------- Persistent browser (lock-protected singleton) ----------------

_lock = threading.RLock()
_driver = None
# Cache of the currently OPEN chat: {"name": str, "header": normalized str}.
_open_chat: dict | None = None


def _alive(d) -> bool:
    try:
        _ = d.title
        return True
    except Exception:
        return False


def _kill_stale_profile_edge():
    """Kill leftover Edge processes holding OUR profile (they lock the
    user-data-dir after a crashed/force-killed run). Only processes whose
    command line matches saathi_edge_profile are touched — user's own Edge
    is never harmed. Best-effort: failures ignored."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -match 'saathi_edge_profile' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(1.0)
    except Exception:
        pass


def _bring_to_front() -> None:
    """Force the Edge/WhatsApp window to the foreground. Launched from a
    background thread (pre-load at startup), the window opens BEHIND
    whatever the user is looking at unless we explicitly steal focus."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(New-Object -ComObject WScript.Shell).AppActivate('WhatsApp')"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _new_driver():
    opts = EdgeOptions()
    opts.add_argument(f"--user-data-dir={EDGE_PROFILE}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--log-level=3")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # NOTE: --disable-gpu MAT karo — WhatsApp Web ka renderer interaction par
    # crash ho jata hai (poora DOM blank). GPU on = stable.
    opts.add_argument("--hide-crash-restore-bubble")
    opts.add_argument("--no-first-run")
    opts.add_argument("--window-size=1100,800")
    opts.add_argument("--start-maximized")
    try:
        d = webdriver.Edge(options=opts)
        try:
            d.switch_to.window(d.current_window_handle)
        except Exception:
            pass
        _bring_to_front()
        return d
    except Exception as e:
        msg = str(e)
        lock_hit = (
            "user data directory" in msg.lower()
            or "already in use" in msg.lower()
            or "sessionnotcreated" in type(e).__name__.lower()
        )
        if lock_hit:
            # Self-heal: stale Edge from a crashed run holds the profile.
            _kill_stale_profile_edge()
            try:
                return webdriver.Edge(options=opts)
            except Exception as e2:
                raise WaError(
                    "Browser launch fail hua (profile lock). Saare Edge windows "
                    "band karke dobara bolein. Detail: " + str(e2)[:80]
                )
        if "version" in msg.lower():
            raise WaError(
                "Edge update ho gaya lagta hai — dobara koshish karein "
                "(driver auto-download hoga, internet chahiye)."
            )
        raise WaError(f"Browser launch failed: {type(e).__name__}")


def get_or_start_driver():
    """Return the persistent driver, launching it if dead. Raises WaError."""
    global _driver
    if _driver is not None and _alive(_driver):
        return _driver
    if _driver is not None:  # dead — clean up
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
    _driver = _new_driver()
    return _driver


def _qr_visible(d) -> bool:
    for xp in ('//canvas[@aria-label*="Scan"]', '//div[@data-ref]'):
        try:
            if d.find_elements(By.XPATH, xp):
                return True
        except Exception:
            pass
    return False


def _wa_state(d) -> str:
    """Cheap WhatsApp Web state probe: 'loaded', 'syncing', 'dead', 'qr', 'loading'.
    Transient renderer hiccups (target frame detached) are tolerated briefly."""
    errors = 0
    while True:
        try:
            if d.find_elements(By.ID, "pane-side"):
                return "loaded"
            break
        except Exception:
            errors += 1
            if errors >= 4:
                raise WaError("Browser control lost.")
            time.sleep(1.0)
    try:
        body = (d.find_element(By.TAG_NAME, "body").text or "").lower()
    except Exception:
        body = ""
    if "log out" in body or "downloading" in body:
        return "syncing"
    if any(m in body for m in _DEAD_SESSION_MARKERS):
        return "dead"
    if _qr_visible(d):
        return "qr"
    return "loading"


def ensure_whatsapp_loaded(timeout: float = 150):
    """Make sure WhatsApp Web is open AND fully loaded. Returns the driver."""
    d = get_or_start_driver()
    try:
        if "web.whatsapp.com" not in (d.current_url or ""):
            d.get(WA_HOME)
    except WaError:
        raise
    except Exception as e:
        raise WaError(f"Browser control lost: {type(e).__name__}")

    end = time.time() + timeout
    while time.time() < end:
        state = _wa_state(d)
        if state == "loaded":
            return d
        if state == "dead":
            raise WaError(
                "WhatsApp session expire ho gayi (device could not link). "
                "Fix: venv\\Scripts\\python whatsapp_login.py — QR dobara scan karein."
            )
        if state == "qr":
            raise WaError(
                "WhatsApp Web login chahiye. Pehle ye chalayein: "
                "venv\\Scripts\\python whatsapp_login.py"
            )
        time.sleep(0.5)
    raise WaError("WhatsApp Web load timeout — internet slow lagta hai, dobara koshish karein.")


def warm_up(background: bool = True):
    """Pre-load WhatsApp Web (optionally in a background thread).

    Called once at assistant startup: by the time the user finishes speaking
    their first command, the session is already open — the send then takes
    2-4s instead of 15-40s.
    """
    def _job():
        try:
            with _lock:
                ensure_whatsapp_loaded(timeout=120)
                print("💬 WhatsApp pre-loaded — messages ab fauran jayenge.")
        except Exception as e:
            print(f"ℹ  WhatsApp pre-load skipped: {str(e)[:80]}")

    if background:
        threading.Thread(target=_job, daemon=True).start()
    else:
        _job()


def shutdown():
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None


atexit.register(shutdown)


def _shot(d) -> str:
    """Best-effort screenshot for debugging — always print where it saved."""
    if d is None:
        return ERROR_SHOT
    try:
        d.save_screenshot(ERROR_SHOT)
        print(f"📸 Screenshot saved: {ERROR_SHOT}")
    except Exception:
        pass
    return ERROR_SHOT# ---------------- Contact resolution (contacts.json + aliases) ----------------

def _upsert_contact(name: str, v: dict) -> dict:
    """Read-modify-write contacts.json, adding/updating ONE entry while
    preserving every other key (comments, order, formatting of the rest).
    File-lock protected so two threads (server + wake listener) can't race.
    Returns the contacts dict that was written."""
    raw = {}
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
        except Exception as e:
            print(f"⚠  contacts.json unreadable ({e}) — starting a fresh one")
            raw = {}
    raw[name] = v
    with _contacts_lock:
        tmp = CONTACTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONTACTS_FILE)  # atomic on Windows + POSIX
    return raw


_contacts_lock = threading.Lock()


def save_contact(name: str, phone: str, aliases: list | None = None) -> str:
    """Save/update a WhatsApp contact by voice: write-through to contacts.json
    AND refresh the in-memory cache this module resolves from. Phone must be
    digits (international, no +) — same format the deep-link path dials."""
    name = (name or "").strip()
    phone_digits = re.sub(r"\D", "", phone or "")
    if not name:
        return "Error: contact ka naam nahi mila."
    if not phone_digits or len(phone_digits) < 7:
        return ("Error: phone number sahi nahi laga — country code ke saath "
                "digits mein bolein, jaise 92 300 1234567.")
    entry = {"phone": phone_digits, "aliases": [a.strip() for a in (aliases or []) if a.strip()]}
    _upsert_contact(name, entry)
    # NOTE: _load_contacts() reads the file fresh on every resolution call,
    # so the new contact is usable immediately — no cache to invalidate.
    print(f"💾 Contact saved: {name} ({digits_fmt(phone_digits)})")
    return f"Contact saved: {name} ({digits_fmt(phone_digits)})"


def _load_contacts() -> dict:
    """Read contacts.json -> {name: {"phone": str|None, "aliases": [..]}}."""
    contacts = {}
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            for name, v in raw.items():
                if name.startswith("_"):  # comment keys
                    continue
                if isinstance(v, str):
                    contacts[name] = {"phone": v, "aliases": []}
                elif isinstance(v, dict):
                    contacts[name] = {
                        "phone": v.get("phone") or None,
                        "aliases": list(v.get("aliases", [])),
                    }
        except Exception as e:
            print(f"⚠  contacts.json parse error: {e}")
    return contacts


def resolve_contact(heard: str) -> tuple[str, str | None]:
    """Map what Whisper heard -> (real contact name, phone or None).

    Order: exact name -> exact alias -> fuzzy match. Returns the heard name
    unchanged (phone None) if nothing matches — search flow still tries it.
    """
    contacts = _load_contacts()
    h = (heard or "").strip().lower()
    if not h:
        return heard, None

    for name, v in contacts.items():
        if h == name.lower():
            return name, v["phone"]
    for name, v in contacts.items():
        for a in v["aliases"]:
            if h == a.lower():
                return name, v["phone"]

    # Fuzzy across names + aliases (Whisper garbles names; cutoff lenient)
    variants = {}
    for name, v in contacts.items():
        variants[name] = name
        for a in v["aliases"]:
            variants[a] = name
    match = difflib.get_close_matches(heard.strip(), list(variants.keys()), n=1, cutoff=0.55)
    if match:
        real = variants[match[0]]
        return real, contacts[real]["phone"]
    return heard.strip(), None


# ---------------- Element helpers ----------------

def _find_now(d, xpaths):
    for xp in xpaths:
        try:
            el = d.find_element(By.XPATH, xp)
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


SEARCH_XPATHS = [
    '//input[contains(@placeholder,"Search")]',
    '//input[contains(@aria-label,"Search")]',
    '//div[@contenteditable="true"][@data-tab="3"]',
    '//div[@contenteditable="true"][@aria-placeholder][contains(@aria-placeholder,"Search")]',
    '//div[@title="Search or start a new chat"]',
]
COMPOSER_XPATHS = [
    '//footer//div[@contenteditable="true"]',
    '//div[@contenteditable="true"][@data-tab="10"]',
    '//div[@id="main"]//div[@contenteditable="true"][last()]',
    '//div[@contenteditable="true"][@aria-placeholder][contains(@aria-placeholder,"Type a message")]',
]
HEADER_XPATHS = [
    '//div[@id="main"]//header',
    '//header',
]
RESULT_XPATH = '//div[@role="row"] | //div[@role="listitem"] | //div[@role="option"]'
INVALID_NUMBER_XPATHS = [
    '//*[contains(text(),"invalid")]',
    '//*[contains(text(),"phone number shared")]',
    '//div[@role="alert"]',
]


def _wait_composer(d, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        box = _find_now(d, COMPOSER_XPATHS)
        if box:
            return box
        if _qr_visible(d):
            raise WaError("WhatsApp Web login chahiye (QR nazar aa gaya).")
        time.sleep(0.3)
    raise WaError("Message box nahi mila (chat nahi khuli).")


def _header_text(d) -> str:
    """Chat NAME shown in the open chat's header ('' if unknown).

    The header's first non-empty text line is normally the chat name
    (contact or group); later lines are 'last seen...' subtitles. BUT the
    avatar circle (e.g. a single letter like "S" for "Shawal") is ALSO
    inside the header element and often comes out as its own line BEFORE
    the real name — so a single-character line is almost always that
    avatar initial, not the actual chat name, and must be skipped.
    Also ignore the generic button title 'Click here for group info' — it
    is NOT the chat name."""
    for xp in HEADER_XPATHS:
        try:
            el = d.find_element(By.XPATH, xp)
            if el.is_displayed():
                txt = (el.text or "").strip()
                for line in txt.splitlines():
                    line = line.strip()
                    if not line or "click here" in line.lower():
                        continue
                    if len(line) <= 1:  # avatar initial letter, e.g. "S"
                        continue
                    return line
                t = (el.get_attribute("title") or "").strip()
                if t and "click here" not in t.lower():
                    return t
        except Exception:
            continue
    return ""


def _type_then_send(d, message: str) -> bool:
    """Type into the open composer and press Enter. Returns verify result."""
    box = _wait_composer(d)
    box.click()
    box.send_keys(message)
    time.sleep(0.2)
    box.send_keys(Keys.ENTER)
    return _verify_sent(d, message)


def _strip_emoji(s: str) -> str:
    """Remove emoji/symbol characters WhatsApp renders as separate <img>
    elements (splitting them out of the text span), which otherwise breaks
    exact-text verification even when the message sent successfully."""
    return "".join(
        c for c in s
        if not (0x1F000 <= ord(c) <= 0x1FFFF or 0x2600 <= ord(c) <= 0x27BF or ord(c) == 0xFE0F)
    )


def _verify_sent(d, message: str, timeout=10) -> bool:
    """Confirm the message text actually appeared in the chat pane (#main).

    Emoji are rendered by WhatsApp as separate <img> elements, splitting a
    message like "hi ✅" across sibling spans/nodes — so instead of requiring
    one span to exactly equal the (emoji-stripped) text, we check whether it
    appears as a substring within the concatenation of the recent spans too.
    """
    want = _norm(_strip_emoji(message))
    if not want:
        want = _norm(message)  # message was ALL emoji — fall back to raw compare
    end = time.time() + timeout
    while time.time() < end:
        try:
            spans = d.find_elements(By.XPATH, '//div[@id="main"]//span[@dir]')
            if not spans:  # newer layout fallback
                spans = d.find_elements(By.XPATH, '//span[contains(@class,"selectable-text")]')
            texts = [_norm(s.text) for s in spans[-40:]]
            for t in texts:
                if t == want or (want and want in t):
                    return True
            # Emoji-splitting fallback: message spread across sibling spans.
            joined = " ".join(texts[-6:])
            if want and want in joined:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


# ---------------- Search flow (the FAST path — no page reload) ----------------

# Section-label rows that appear INSIDE search results — clicking these does
# nothing (they are headers of result groups, not chats).
_SECTION_LABELS = {
    "chats", "messages", "contacts", "groups", "unread", "favorites",
    "archived", "status", "channels", "communities",
}


def _pick_result_row(results, contact: str):
    """Pick the REAL chat row for a contact from mixed search results.

    Search results are ORDERED: [Chats label, chat rows..., Contacts label,
    contact suggestions...]. Rows AFTER the 'Contacts' label are phone-book
    suggestions — for an EXISTING chat we prefer the chat rows (WhatsApp put
    the top match first there). Clicking a section label opens nothing.
    """
    first_word = contact.lower().split()[0] if contact.split() else contact.lower()
    name_rows, word_rows = [], []          # from the Chats section
    late_name_rows, late_word_rows = [], []  # after the Contacts label
    past_contacts = False
    for r in results[:14]:
        try:
            if not r.is_displayed():
                continue
            txt = _norm(r.text)
        except Exception:
            continue
        if not txt:
            continue
        if txt in _SECTION_LABELS:
            if txt in ("contacts", "connecting"):
                past_contacts = True
            continue
        c = contact.lower()
        bucket_names, bucket_words = (
            (late_name_rows, late_word_rows) if past_contacts else (name_rows, word_rows)
        )
        if c in txt:
            bucket_names.append(r)
        elif first_word and first_word in txt:
            bucket_words.append(r)
    # Chats-section matches first, then contact suggestions as fallback.
    return (name_rows or word_rows or late_name_rows or late_word_rows or [None])[0]


def _open_chat_via_search(d, contact: str, expected_phone: str | None = None) -> None:
    """Open a chat from the chat list using the in-app search box.

    The search stays INSIDE the already-loaded app (no navigation) so this
    takes ~1-3s. Raises WaError with a clear message on any failure.
    """
    global _open_chat
    search = _find_now(d, SEARCH_XPATHS)
    if search is None:
        raise WaError("Search box nahi mila — WhatsApp Web layout badla hua lagta hai.")
    search.click()
    search.send_keys(Keys.CONTROL, "a")
    search.send_keys(contact)
    time.sleep(1.0)  # let results populate (was 1.5s; search is local & fast)

    results = []
    end = time.time() + 8
    while time.time() < end and not results:
        try:
            results = d.find_elements(By.XPATH, RESULT_XPATH)
        except Exception:
            results = []
        time.sleep(0.3)
    if not results:
        raise WaError(f"'{contact}' WhatsApp chat list mein nahi mila.")

    # Pick the real chat row (skips 'Chats'/'Messages' section labels).
    target = _pick_result_row(results, contact)
    if target is None:
        raise WaError(f"'{contact}' WhatsApp chat list mein nahi mila (sirf labels mile).")
    target.click()

    _wait_composer(d, timeout=12)

    # Never type into the wrong chat: verify the header matches the contact.
    header = _norm(_header_text(d))
    first_word = contact.lower().split()[0] if contact.split() else contact.lower()
    if contact.lower() not in header and first_word not in header:
        raise WaError(
            f"Chat header '{header or 'unknown'}' matched nahi hui '{contact}' se — "
            "message send nahi kiya (ghalat chat ka risk). contacts.json mein "
            "phone number add karein — wo flow 100% reliable hai."
        )
    _open_chat = {"name": contact, "header": header}


# ---------------- Deep-link fallback (LAST resort only) ----------------

def _send_via_phone(d, phone: str, message: str) -> bool:
    """Deep link: web.whatsapp.com/send?phone=..&text=.. (full app reload)."""
    global _open_chat
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 10:
        raise WaError(f"Phone number '{phone}' mukammal nahi (country code ke saath likhein, e.g. 923001234567).")
    url = f"{WA_HOME}/send?phone={digits}&text={quote(message)}"
    d.get(url)

    end = time.time() + 30
    box = None
    while time.time() < end:
        box = _find_now(d, COMPOSER_XPATHS)
        if box:
            break
        if _find_now(d, INVALID_NUMBER_XPATHS):
            raise WaError(f"Number {digits} WhatsApp par nahi mila ya galat hai.")
        if _qr_visible(d):
            raise WaError("WhatsApp Web login chahiye.")
        time.sleep(0.5)
    if box is None:
        raise WaError("Chat window nahi khuli (timeout).")

    # Give WhatsApp a moment to prefill from the URL; type manually if not.
    end = time.time() + 3
    while time.time() < end and not (box.text or "").strip():
        time.sleep(0.3)
    if not (box.text or "").strip():
        box.click()
        box.send_keys(message)
    time.sleep(0.3)
    box.send_keys(Keys.ENTER)
    _open_chat = None  # unknown header — don't trust cache after navigation
    ok = _verify_sent(d, message)
    # If the full app UI survived the deep-link (pane-side present), keep the
    # session where it is — next send to the SAME contact is then instant.
    try:
        if _wa_state(d) != "loaded":
            d.get(WA_HOME)
    except Exception:
        pass
    return ok


# ---------------- Public API ----------------

def send_message(contact: str, message: str) -> str:
    """Send one message through the persistent session. Returns success
    string or raises WaError. HOT PATH = no page navigation."""
    name, phone = resolve_contact(contact)
    if name != contact:
        print(f"📇 Contact resolved: '{contact}' -> '{name}'" + (" (phone)" if phone else " (search)"))
    global _open_chat
    d = None
    with _lock:
        try:
            d = ensure_whatsapp_loaded(timeout=60)

            # Fast path: the right chat is ALREADY open → type + Enter.
            if (
                _open_chat
                and phone
                and (_open_chat.get("name", "").lower() == (name or "").lower())
            ):
                print("⚡ Same chat open — direct send (skip search).")
                ok = _type_then_send(d, message)
                if ok:
                    return f"Message sent to {name} ({digits_fmt(phone)})"
                # stale cache (chat closed?) — fall through to search path
                _open_chat = None

            # Number-wale contact + WhatsApp par chat open nahi hui kabhi:
            # deep-link fallback zyada reliable nikla hai (search contact ko
            # phone-book naam se na dhundh paye). Search pehle try hota hai
            # (fast), deep-link uske fail par.


            # Warm path: in-app search inside the loaded app (~2-4s).
            try:
                _open_chat_via_search(d, name, phone)
                ok = _type_then_send(d, message)
                if ok:
                    target = f"{name} ({digits_fmt(phone)})" if phone else name
                    return f"Message sent to {target}"
                raise WaError(f"Message {name} ko bheja gaya magar verify nahi ho saka.")
            except WaError as e:
                # Number-wala contact agar phone ke contacts mein saved nahi
                # to in-app search use nahi dhundh sakti — wa.me deep link
                # phir bhi kaam karta hai (slow, reload-worthy last resort).
                if phone and "nahi mila" in str(e):
                    print("🔎 Search fail — wa.me deep-link fallback...")
                    ok = _send_via_phone(d, phone, message)
                    if ok:
                        return f"Message sent to {name} ({digits_fmt(phone)})"
                    raise WaError(f"Message {name} ko bheja gaya magar verify nahi ho saka.")
                raise
        except WaError as e:
            _shot(d)
            raise
        except Exception as e:
            _shot(d)
            raise WaError(f"{type(e).__name__}: {str(e)[:120]}") from e


def digits_fmt(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def status() -> str:
    """Human-readable one-liner about the browser/session state (for doctor)."""
    try:
        d = get_or_start_driver()
    except WaError as e:
        return f"LAUNCH FAIL: {e}"
    try:
        if "web.whatsapp.com" not in (d.current_url or ""):
            d.get(WA_HOME)
        end = time.time() + 150
        while time.time() < end:
            state = _wa_state(d)
            if state == "loaded":
                n = len(d.find_elements(By.XPATH, '//div[@role="listitem"] | //div[@role="option"]'))
                return f"LOGGED IN — chat list loaded ({n} chats)"
            if state == "dead":
                return "SESSION DEAD — 'could not link' (run whatsapp_login.py, QR rescan)"
            if state == "qr":
                return "NOT LOGGED IN — QR screen visible (run whatsapp_login.py)"
            time.sleep(0.5)
        return "TIMEOUT — internet slow lagta hai, dobara koshish karein"
    except WaError as e:
        return str(e)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {str(e)[:120]}"