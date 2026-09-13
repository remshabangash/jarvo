"""Linux resolver — .desktop file scan + PATH executables via shutil.which."""
import os
import shutil
import subprocess
import webbrowser

from ._common import NOT_AN_APP, URL_APPS, looks_like_domain

_DESKTOP_CACHE: dict | None = None
_XDG_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
]


def _desktop_apps() -> dict:
    """lowercase app name -> Name= field from .desktop files (cached once)."""
    global _DESKTOP_CACHE
    if _DESKTOP_CACHE is not None:
        return _DESKTOP_CACHE
    apps: dict = {}
    for root in _XDG_DIRS:
        if os.path.isdir(root):
            for f in os.listdir(root):
                if not f.endswith(".desktop"):
                    continue
                path = os.path.join(root, f)
                display, exec_cmd, hidden = None, None, False
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        in_main = False
                        for line in fh:
                            line = line.strip()
                            if line.startswith("["):
                                in_main = (line == "[Desktop Entry]")
                                continue
                            if not in_main or "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            k = k.strip().lower()
                            if k == "name" and display is None:
                                display = v.strip()
                            elif k == "exec" and exec_cmd is None:
                                exec_cmd = v.strip()
                            elif k == "hidden" and v.strip().lower() in ("true", "1"):
                                hidden = True
                            elif k == "notshowin" and "unity" in v.lower():
                                hidden = True
                except OSError:
                    continue
                if hidden or not display or not exec_cmd:
                    continue
                key = display.lower().strip()
                if key and key not in apps:
                    apps[key] = (display, f)
    _DESKTOP_CACHE = apps
    return apps


def _launch_desktop(desktop_file: str) -> bool:
    """Launch via gio (honors the .desktop Exec line properly), else gtk-launch."""
    try:
        r = subprocess.run(
            ["gio", "launch", os.path.join("/usr/share/applications", desktop_file)],
            capture_output=True, text=True, timeout=8,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        r = subprocess.run(
            ["gtk-launch", desktop_file.removesuffix(".desktop")],
            capture_output=True, text=True, timeout=8,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


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

    # 1. .desktop entries (exact, then fuzzy contains-match)
    apps = _desktop_apps()
    target = None
    if key in apps:
        target = apps[key]
    elif len(key) >= 4:
        for name, val in apps.items():
            if key in name or (len(name) >= 4 and name in key):
                target = val
                break
    if target:
        if _launch_desktop(target[1]):
            return f"Opened {spoken}"

    # 2. PATH executables (terminal tools: gedit, vlc, code, htop…)
    exe = shutil.which(key.replace(" ", "-")) or shutil.which(key.replace(" ", "_"))
    if exe:
        try:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opened {spoken}"
        except OSError:
            pass

    # 3. Domain-like input -> browser
    if looks_like_domain(key):
        webbrowser.open(f"https://{spoken}")
        return f"Opened {spoken} in browser"

    return f"Error: {spoken} open nahi hua. App ka naam check karein."
