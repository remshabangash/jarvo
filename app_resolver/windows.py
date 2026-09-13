"""Windows resolver — Start Menu .lnk scan, exe fallback, UWP apps."""
import os
import subprocess
import sys
import webbrowser

import winfocus
from ._common import NOT_AN_APP, URL_APPS, looks_like_domain

# Known exe names (fallback for apps without Start Menu shortcuts)
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
    if s in _UWP_CACHE:
        return f"shell:AppsFolder\\{_UWP_CACHE[s]}"
    for name, appid in _UWP_CACHE.items():
        if (len(s) >= 4 and s in name) or (len(name) >= 4 and name in s):
            return f"shell:AppsFolder\\{appid}"
    return None


def resolve_and_open(app_name: str) -> str:
    """Resolve ANY spoken app name and launch it. Returns a result string
    starting with 'Error:' on failure."""
    spoken = (app_name or "").strip()
    key = spoken.lower().strip()
    if not key:
        return "Error: koi app ka naam nahi mila."

    if key in NOT_AN_APP:
        return f"Error: '{spoken}' koi app nahi lagti."

    url = URL_APPS.get(key)
    if url:
        webbrowser.open(url)
        winfocus.bring_to_front_async(spoken)
        return f"Opened {spoken}"

    lnk_apps = _start_menu_apps()
    if key in lnk_apps:
        try:
            os.startfile(lnk_apps[key])
            winfocus.bring_to_front_async(spoken)
            return f"Opened {spoken}"
        except OSError:
            pass
    if len(key) >= 4:
        for name, path in lnk_apps.items():
            if key in name or (len(name) >= 4 and name in key):
                try:
                    os.startfile(path)
                    winfocus.bring_to_front_async(spoken)
                    return f"Opened {spoken}"
                except OSError:
                    continue

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

    uwp = _uwp_lookup(key)
    if uwp:
        try:
            os.startfile(uwp)
            winfocus.bring_to_front_async(spoken)
            return f"Opened {spoken}"
        except OSError:
            pass

    if looks_like_domain(key):
        webbrowser.open(f"https://{spoken}")
        winfocus.bring_to_front_async(spoken)
        return f"Opened {spoken} in browser"

    query = f"{spoken} download" if len(key) < 25 else spoken
    from executor import web_search  # lazy: avoids circular import at module load
    web_search(query)
    winfocus.bring_to_front_async(spoken)
    return f"'{spoken}' laptop par nahi mili — browser mein search khol di."
