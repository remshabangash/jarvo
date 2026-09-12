"""General-purpose CONTROLLED web browser for voice commands like
"is par click karo" / "click on Show More" / "neeche scroll karo".

Why this exists: open_app() opens websites via webbrowser.open(), which
launches the user's normal default browser — Python has NO control over
that tab (can't click links in it, can't read its content). To let the
user say "open X website" and then keep giving follow-up commands like
"click on this link" WITHOUT repeating the whole request, we need our own
Selenium-driven browser window instead (same pattern as whatsapp_bot.py),
kept open across turns so follow-up commands act on the SAME page.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import threading
import time
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException

BROWSER_PROFILE = os.path.join(os.path.expanduser("~"), "saathi_browser_profile")
ERROR_SHOT = os.path.join(os.path.dirname(__file__), "browser_error.png")

_MAX_PAGE_TEXT_CHARS = 1500
_DEFAULT_ZOOM_STEP = 0.1
_MIN_ZOOM, _MAX_ZOOM = 0.5, 2.0


class BrowserError(Exception):
    """Clear, speakable error — the assistant reads this aloud on failure."""


_lock = threading.RLock()
_driver = None
_zoom_level = 1.0


def _alive(d) -> bool:
    try:
        _ = d.title
        return True
    except Exception:
        return False


def _kill_stale_profile_edge():
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -match 'saathi_browser_profile' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
            capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(1.0)
    except Exception:
        pass


def _bring_to_front() -> None:
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(New-Object -ComObject WScript.Shell).AppActivate('Edge')"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _new_driver():
    opts = EdgeOptions()
    opts.add_argument(f"--user-data-dir={BROWSER_PROFILE}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--log-level=3")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--hide-crash-restore-bubble")
    opts.add_argument("--window-size=1200,850")
    opts.add_argument("--start-maximized")
    try:
        d = webdriver.Edge(options=opts)
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
            _kill_stale_profile_edge()
            try:
                return webdriver.Edge(options=opts)
            except Exception as e2:
                raise BrowserError(
                    "Browser launch fail hua (profile lock). Saare Edge windows "
                    "band karke dobara bolein. Detail: " + str(e2)[:80]
                )
        raise BrowserError(f"Browser launch failed: {type(e).__name__}")


def _get_driver():
    global _driver, _zoom_level
    if _driver is not None and _alive(_driver):
        return _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
    _driver = _new_driver()
    _zoom_level = 1.0
    return _driver


def _require_driver():
    global _driver
    if _driver is None or not _alive(_driver):
        raise BrowserError("Pehle koi website kholni hogi.")
    return _driver


def shutdown():
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None


atexit.register(shutdown)


def _shot(d) -> None:
    try:
        d.save_screenshot(ERROR_SHOT)
    except Exception:
        pass


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


def _safe_click(d, el) -> None:
    try:
        el.click()
    except ElementClickInterceptedException:
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        d.execute_script("arguments[0].click();", el)


# ---------------- Public API: navigation ----------------

def open_page(target: str) -> str:
    with _lock:
        d = _get_driver()
        t = (target or "").strip()
        if not t:
            raise BrowserError("Koi website ya search term nahi mila.")
        if "." in t and " " not in t and not t.startswith("http"):
            url = t if t.startswith("http") else f"https://{t}"
        elif t.startswith("http"):
            url = t
        else:
            url = f"https://www.google.com/search?q={quote(t)}"
        try:
            d.get(url)
        except Exception as e:
            _shot(d)
            raise BrowserError(f"Website open nahi hui: {type(e).__name__}")
        _bring_to_front()
        return f"Opened {t}"


def go_back() -> str:
    with _lock:
        d = _require_driver()
        try:
            d.back()
        except Exception as e:
            raise BrowserError(f"Peeche nahi ja saka: {type(e).__name__}")
        return "Went back"


def refresh() -> str:
    with _lock:
        d = _require_driver()
        try:
            d.refresh()
        except Exception as e:
            raise BrowserError(f"Refresh nahi ho saka: {type(e).__name__}")
        return "Page refreshed"


# ---------------- Public API: interaction ----------------

def click_text(target: str, timeout: float = 6.0) -> str:
    with _lock:
        d = _require_driver()
        want = _norm(target)
        if not want:
            raise BrowserError("Kis cheez par click karna hai, wo nahi mila.")

        end = time.time() + timeout
        xp = (
            '//a | //button | //*[@role="button"] | //*[@onclick] | '
            '//input[@type="submit" or @type="button"]'
        )
        while time.time() < end:
            try:
                candidates = d.find_elements(By.XPATH, xp)
            except Exception:
                candidates = []
            exact, partial = None, None
            for el in candidates:
                try:
                    if not el.is_displayed():
                        continue
                    txt = _norm(el.text) or _norm(el.get_attribute("aria-label") or "") \
                        or _norm(el.get_attribute("title") or "") \
                        or _norm(el.get_attribute("value") or "")
                    if not txt:
                        continue
                    if txt == want and exact is None:
                        exact = el
                    elif want in txt and partial is None:
                        partial = el
                except Exception:
                    continue
            target_el = exact or partial
            if target_el is not None:
                _safe_click(d, target_el)
                return f"Clicked '{target}'"
            time.sleep(0.3)
        _shot(d)
        raise BrowserError(f"'{target}' naam ka koi clickable element nahi mila is page par.")


def type_into(label_hint: str, text: str, timeout: float = 6.0) -> str:
    with _lock:
        d = _require_driver()
        want = _norm(label_hint)
        text = text or ""

        end = time.time() + timeout
        while time.time() < end:
            try:
                fields = d.find_elements(
                    By.XPATH,
                    '//input[not(@type) or @type="text" or @type="search" '
                    'or @type="email" or @type="url" or @type="tel"] | //textarea'
                )
            except Exception:
                fields = []

            best = None
            for el in fields:
                try:
                    if not el.is_displayed() or not el.is_enabled():
                        continue
                    hint = " ".join([
                        _norm(el.get_attribute("placeholder") or ""),
                        _norm(el.get_attribute("name") or ""),
                        _norm(el.get_attribute("aria-label") or ""),
                        _norm(el.get_attribute("id") or ""),
                    ])
                    if not want:
                        best = el
                        break
                    if want in hint:
                        best = el
                        break
                except Exception:
                    continue

            if best is not None:
                try:
                    best.clear()
                except Exception:
                    pass
                best.send_keys(text)
                return f"Typed '{text}' in field"
            time.sleep(0.3)

        _shot(d)
        hint_msg = f"'{label_hint}' naam ka" if label_hint else "koi"
        raise BrowserError(f"{hint_msg} field nahi mila is page par.")


def press_enter() -> str:
    with _lock:
        d = _require_driver()
        try:
            active = d.switch_to.active_element
            active.send_keys(Keys.RETURN)
        except Exception as e:
            raise BrowserError(f"Enter nahi dab saka: {type(e).__name__}")
        return "Pressed Enter"


def scroll(direction: str) -> str:
    with _lock:
        d = _require_driver()
        amount = 700 if "down" in (direction or "").lower() else -700
        try:
            d.execute_script(f"window.scrollBy(0, {amount});")
        except Exception as e:
            raise BrowserError(f"Scroll nahi ho saka: {type(e).__name__}")
        return f"Scrolled {'down' if amount > 0 else 'up'}"


# ---------------- Public API: reading page content ----------------

def get_page_text(max_chars: int = _MAX_PAGE_TEXT_CHARS) -> str:
    with _lock:
        d = _require_driver()
        try:
            body = d.find_element(By.TAG_NAME, "body")
            text = " ".join(body.text.split())
        except Exception as e:
            raise BrowserError(f"Page text nahi mil saka: {type(e).__name__}")
        if not text:
            raise BrowserError("Is page par koi text nahi mila.")
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "..."
        return text


def get_page_title() -> str:
    with _lock:
        d = _require_driver()
        try:
            title = (d.title or "").strip()
        except Exception as e:
            raise BrowserError(f"Title nahi mil saka: {type(e).__name__}")
        return title or "Is page ka title nahi mila."


def get_link_url(target: str, timeout: float = 6.0) -> str:
    with _lock:
        d = _require_driver()
        want = _norm(target)
        if not want:
            raise BrowserError("Kis link ka URL chahiye, wo nahi mila.")

        end = time.time() + timeout
        while time.time() < end:
            try:
                links = d.find_elements(By.TAG_NAME, "a")
            except Exception:
                links = []
            exact, partial = None, None
            for el in links:
                try:
                    if not el.is_displayed():
                        continue
                    txt = _norm(el.text)
                    if not txt:
                        continue
                    if txt == want and exact is None:
                        exact = el
                    elif want in txt and partial is None:
                        partial = el
                except Exception:
                    continue
            found = exact or partial
            if found is not None:
                href = found.get_attribute("href")
                return href or "Is link ka URL nahi mila."
            time.sleep(0.3)
        raise BrowserError(f"'{target}' naam ka koi link nahi mila is page par.")


# ---------------- Public API: tabs ----------------

def new_tab(url: str = "") -> str:
    with _lock:
        d = _get_driver()
        try:
            d.execute_script("window.open('');")
            d.switch_to.window(d.window_handles[-1])
        except Exception as e:
            raise BrowserError(f"Naya tab nahi khul saka: {type(e).__name__}")
        _bring_to_front()
        if url:
            return open_page(url)
        return "New tab opened"


def switch_tab(index: int) -> str:
    with _lock:
        d = _require_driver()
        handles = d.window_handles
        if not handles:
            raise BrowserError("Koi tab khuli nahi hai.")
        if index < 0 or index >= len(handles):
            raise BrowserError(f"Sirf {len(handles)} tab(s) khuli hain — ye number nahi milta.")
        try:
            d.switch_to.window(handles[index])
        except Exception as e:
            raise BrowserError(f"Tab switch nahi ho saka: {type(e).__name__}")
        _bring_to_front()
        return f"Switched to tab {index + 1}"


def close_tab() -> str:
    global _driver
    with _lock:
        d = _require_driver()
        try:
            handles = d.window_handles
            d.close()
        except Exception as e:
            raise BrowserError(f"Tab band nahi ho saka: {type(e).__name__}")

        try:
            still_open = d.window_handles
        except Exception:
            still_open = []

        if not still_open:
            _driver = None
            return "Tab band kar di — browser bhi band ho gaya."

        try:
            d.switch_to.window(still_open[-1])
        except Exception:
            pass
        return "Tab band kar di"


# ---------------- Public API: display ----------------

def zoom(direction: str) -> str:
    global _zoom_level
    with _lock:
        d = _require_driver()
        step = _DEFAULT_ZOOM_STEP if "in" in (direction or "").lower() else -_DEFAULT_ZOOM_STEP
        _zoom_level = max(_MIN_ZOOM, min(_MAX_ZOOM, _zoom_level + step))
        try:
            d.execute_script(f"document.body.style.zoom='{_zoom_level}';")
        except Exception as e:
            raise BrowserError(f"Zoom nahi ho saka: {type(e).__name__}")
        return f"Zoomed to {int(_zoom_level * 100)}%"


def reset_zoom() -> str:
    global _zoom_level
    with _lock:
        d = _require_driver()
        _zoom_level = 1.0
        try:
            d.execute_script("document.body.style.zoom='1';")
        except Exception as e:
            raise BrowserError(f"Zoom reset nahi ho saka: {type(e).__name__}")
        return "Zoom reset to 100%"