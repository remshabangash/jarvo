"""macOS resolver — `open -a` for known apps + /Applications folder scan."""
import os
import subprocess
import webbrowser

from ._common import NOT_AN_APP, URL_APPS, looks_like_domain

# Common spoken name -> real .app name for `open -a`
_APP_NAMES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "browser": "Safari",
    "notepad": "TextEdit",
    "textedit": "TextEdit",
    "calculator": "Calculator",
    "calc": "Calculator",
    "preview": "Preview",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "terminal": "Terminal",
    "finder": "Finder",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
}

_APPS_CACHE: dict | None = None


def _installed_apps() -> dict:
    """lowercase name (without .app) -> display name, scanned once, cached."""
    global _APPS_CACHE
    if _APPS_CACHE is not None:
        return _APPS_CACHE
    apps: dict = {}
    for root in ("/Applications", os.path.expanduser("~/Applications")):
        if os.path.isdir(root):
            for f in os.listdir(root):
                if f.lower().endswith(".app"):
                    name = f[:-4].lower().strip()
                    apps.setdefault(name, f[:-4])
    _APPS_CACHE = apps
    return apps


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
        return f"Opened {spoken}"

    # Known mapping first
    if key in _APP_NAMES:
        try:
            result = subprocess.run(
                ["open", "-a", _APP_NAMES[key]],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return f"Opened {spoken}"
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Scan /Applications (fuzzy contains-match both ways)
    installed = _installed_apps()
    if key in installed:
        target = installed[key]
    else:
        target = None
        if len(key) >= 4:
            for name, display in installed.items():
                if key in name or (len(name) >= 4 and name in key):
                    target = display
                    break
    if target:
        try:
            result = subprocess.run(
                ["open", "-a", target],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return f"Opened {spoken}"
        except (OSError, subprocess.TimeoutExpired):
            pass

    if looks_like_domain(key):
        webbrowser.open(f"https://{spoken}")
        return f"Opened {spoken} in browser"

    return f"Error: {spoken} open nahi hua. App ka naam check karein."
