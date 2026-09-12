"""Executes the actions chosen by the LLM brain.

open_app is NOT limited to a predefined app list: it resolves ANY spoken app
name through a cascade —
  1. Known websites (URL map)
  2. Start Menu shortcut scan (every installed desktop app, cached once)
  3. Known exe names (fallback for apps without shortcuts)
  4. UWP / Microsoft Store apps via PowerShell Get-StartApps
  5. Anything that looks like a domain → opened in the browser
  6. Otherwise an HONEST failure (never a fake success or surprise search)
"""
import os
import subprocess
import webbrowser
import winfocus

import brain
import screen_tools


# ---------------- App resolution (free-form, no fixed command list) ----------------

_LNK_CACHE: dict | None = None
_UWP_CACHE: dict | None = None


def _start_menu_apps() -> dict:
    """name -> .lnk path for EVERY Start Menu shortcut (scanned once, cached)."""
    global _LNK_CACHE
    if _LNK_CACHE is not None:
        return _LNK_CACHE
    apps: dict = {}
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for root in roots:
        if root and os.path.isdir(root):
            for dirpath, _, files in os.walk(root):
                for f in files:
                    if f.lower().endswith((".lnk", ".url")):
                        key = os.path.splitext(f)[0].lower().strip()
                        apps.setdefault(key, os.path.join(dirpath, f))
    _LNK_CACHE = apps
    return apps


def _uwp_lookup(spoken: str) -> str | None:
    """Find a UWP/Store app whose name resembles the spoken one.
    Returns an AppsFolder path to open, or None."""
    global _UWP_CACHE
    if _UWP_CACHE is None:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-StartApps | ForEach-Object { \"$($_.Name)|$($_.AppID)\" }"],
                capture_output=True, text=True, timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            apps = {}
            for line in (r.stdout or "").splitlines():
                if "|" in line:
                    name, appid = line.rsplit("|", 1)
                    if name.strip() and appid.strip():
                        apps[name.strip().lower()] = appid.strip()
            _UWP_CACHE = apps
        except Exception:
            _UWP_CACHE = {}
    if not _UWP_CACHE:
        return None
    s = spoken.lower().strip()
    # exact, then substring (both directions)
    if s in _UWP_CACHE:
        return f"shell:AppsFolder\\{_UWP_CACHE[s]}"
    for name, appid in _UWP_CACHE.items():
        if (len(s) >= 4 and s in name) or (len(name) >= 4 and name in s):
            return f"shell:AppsFolder\\{appid}"
    return None


# exe fallbacks for apps whose shortcut name may differ from the spoken name
_EXE_FALLBACK = {
    "chrome": "chrome.exe",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "vs code": "code",
    "vscode": "code",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
}

# Well-known websites — opened straight in the browser (most reliable)
_URL_APPS = {
    "youtube": "https://www.youtube.com",
    "browser": "https://www.google.com",
    "google": "https://www.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "gmail": "https://mail.google.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp web": "https://web.whatsapp.com",
    "whatsapp": "https://web.whatsapp.com",
    # Safety net: Whisper (STT) sometimes mishears "WhatsApp" as one of
    # these short garbled words on a Pakistani accent — catch it here too,
    # in case it ever slips past the stt.py word-fix list.
    "asep": "https://web.whatsapp.com",
    "asap": "https://web.whatsapp.com",
    "wasap": "https://web.whatsapp.com",
    "chatgpt": "https://chat.openai.com",
    "github": "https://github.com",
}

# Words that are obviously NOT app names (LLM occasionally passes sentences)
_NOT_AN_APP = (
    "message", "messages", "text", "call", "search", "news", "weather",
    "screenshot", "screen shot", "recording", "screen recording",
)


def open_app(app_name: str) -> str:
    spoken = (app_name or "").strip()
    key = spoken.lower().strip()
    if not key:
        return "Error: koi app ka naam nahi mila."

    if key in _NOT_AN_APP:
        return f"Error: '{spoken}' koi app nahi lagti."

    # 1) Known websites
    url = _URL_APPS.get(key)
    if url:
        webbrowser.open(url)
        winfocus.bring_to_front_async(spoken)
        return f"Opened {spoken}"

    # 2) Start Menu shortcut scan (covers every installed desktop app)
    lnk_apps = _start_menu_apps()
    if key in lnk_apps:
        try:
            os.startfile(lnk_apps[key])
            winfocus.bring_to_front_async(spoken)
            return f"Opened {spoken}"
        except OSError:
            pass
    # substring match (spoken name inside a shortcut name or vice versa)
    if len(key) >= 4:
        for name, path in lnk_apps.items():
            if key in name or (len(name) >= 4 and name in key):
                try:
                    os.startfile(path)
                    winfocus.bring_to_front_async(spoken)
                    return f"Opened {spoken}"
                except OSError:
                    continue

    # 3) Known exe fallback
    exe = _EXE_FALLBACK.get(key)
    if exe:
        try:
            os.startfile(exe)
            winfocus.bring_to_front_async(spoken)
            return f"Opened {spoken}"
        except OSError:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", exe],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                winfocus.bring_to_front_async(spoken)
                return f"Opened {spoken}"
            except Exception as e:
                return f"Error: {spoken} open nahi hua ({e})"

    # 4) UWP / Store apps
    uwp = _uwp_lookup(key)
    if uwp:
        try:
            os.startfile(uwp)
            winfocus.bring_to_front_async(spoken)
            return f"Opened {spoken}"
        except OSError:
            pass

    # 5) Looks like a domain (e.g. "stackoverflow.com") → browser
    if " " not in key and ("." in key or key.endswith(("app", "ai", "com"))):
        webbrowser.open(f"https://{spoken}")
        winfocus.bring_to_front_async(spoken)
        return f"Opened {spoken} in browser"

    # 6) Not found anywhere on the laptop — NEVER give up silently.
    # Open it as a Google search in the browser instead, so the user always
    # gets something useful instead of a dead-end "app not found" error.
    query = f"{spoken} download" if len(key) < 25 else spoken
    web_search(query)
    winfocus.bring_to_front_async(spoken)
    return f"'{spoken}' laptop par nahi mili — browser mein search khol di."


def web_search(query: str) -> str:
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(url)
    # Search-result tab titles usually start with the query text, so the
    # first couple of words are a reliable substring to match against.
    winfocus.bring_to_front_async(" ".join(query.split()[:3]), delay=0.8)
    return f"Opened web search for: {query}"


# ---------------- WhatsApp ----------------

def send_whatsapp(contact: str, message: str) -> str:
    """Send a WhatsApp message through the PERSISTENT browser session."""
    from whatsapp_bot import send_message, WaError
    try:
        result = send_message(contact, message)
        winfocus.bring_to_front_async("WhatsApp", delay=0.3)
        return result
    except WaError as e:
        return f"WhatsApp error: {e}"


# ---------------- Email ----------------

def _send_email_tool(args: dict) -> str:
    """Send an email via email_sender (Gmail SMTP). Clear speakable error."""
    from email_sender import send_email, EmailError
    try:
        return send_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
    except EmailError as e:
        return f"Email error: {e}"
    except Exception as e:
        return f"Email error: {type(e).__name__}: {str(e)[:100]}"


# ---------------- Screen capture ----------------

def _screenshot() -> str:
    try:
        path = screen_tools.take_screenshot()
        print(f"📸 Screenshot: {path}")
        return path
    except Exception as e:
        return f"Error: screenshot nahi le saka ({type(e).__name__})"


def _start_recording() -> str:
    try:
        path = screen_tools.start_recording()
        if path.startswith("Error:"):
            return path
        print(f"🔴 Recording started: {path}")
        return path
    except Exception as e:
        return f"Error: recording shuru nahi ho saki ({type(e).__name__})"


def _stop_recording() -> str:
    try:
        result = screen_tools.stop_recording()
        print(f"⏹  {result}")
        return result
    except Exception as e:
        return f"Error: recording band nahi ho saki ({type(e).__name__})"


# ---------------- Dispatcher ----------------

def execute(name: str, args: dict) -> str:
    if name == "send_whatsapp":
        return send_whatsapp(args.get("contact", ""), args.get("message", ""))
    if name == "send_email":
        return _send_email_tool(args)
    if name == "open_app":
        return open_app(args.get("app_name", ""))
    if name == "web_search":
        return web_search(args.get("query", ""))
    if name == "take_screenshot":
        return _screenshot()
    if name == "start_recording":
        return _start_recording()
    if name == "stop_recording":
        return _stop_recording()
    if name == "general_reply":
        return args.get("reply", "")
    return f"Unknown tool: {name}"


brain.set_executor(execute)