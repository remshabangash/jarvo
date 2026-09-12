"""winfocus.py — force a just-opened window to the foreground.

Windows normally blocks background processes from "stealing" focus — when
SAATHI opens WhatsApp, Notepad, a browser tab, etc., Windows only flashes
its taskbar icon instead of bringing it to the front. This uses the
standard AttachThreadInput trick to work around that, so things SAATHI
opens actually show up on screen instead of needing a manual taskbar click.

Best-effort only: if the window can't be found (wrong title guess, app is
slow to open, etc.) this just does nothing rather than raising.
"""
import ctypes
import time

try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
except Exception:
    _user32 = None
    _kernel32 = None

SW_RESTORE = 9


def bring_to_front(title_substring: str, timeout: float = 6.0, poll: float = 0.25) -> bool:
    """Find a visible top-level window whose title contains
    `title_substring` (case-insensitive) and force it to the foreground.
    Polls for up to `timeout` seconds since the window may still be
    launching. Returns True if a window was found and focused."""
    if _user32 is None or not title_substring:
        return False

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    needle = title_substring.lower()
    found = {"hwnd": None}

    def _enum(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        if needle in buf.value.lower():
            found["hwnd"] = hwnd
            return False
        return True

    cb = WNDENUMPROC(_enum)
    deadline = time.time() + timeout
    hwnd = None
    while time.time() < deadline and hwnd is None:
        found["hwnd"] = None
        _user32.EnumWindows(cb, 0)
        hwnd = found["hwnd"]
        if hwnd is None:
            time.sleep(poll)

    if not hwnd:
        return False
    return _force_foreground(hwnd)


def _force_foreground(hwnd) -> bool:
    try:
        fg = _user32.GetForegroundWindow()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None)
        cur_thread = _kernel32.GetCurrentThreadId()
        target_thread = _user32.GetWindowThreadProcessId(hwnd, None)

        _user32.AttachThreadInput(cur_thread, fg_thread, True)
        _user32.AttachThreadInput(cur_thread, target_thread, True)
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)
        _user32.BringWindowToTop(hwnd)
        _user32.AttachThreadInput(cur_thread, fg_thread, False)
        _user32.AttachThreadInput(cur_thread, target_thread, False)
        return True
    except Exception:
        return False


def bring_to_front_async(title_substring: str, delay: float = 0.6, timeout: float = 6.0):
    """Fire-and-forget version — call right after launching something so the
    caller doesn't have to block waiting for the window to appear."""
    import threading

    def _run():
        time.sleep(delay)
        bring_to_front(title_substring, timeout=timeout)

    threading.Thread(target=_run, daemon=True).start()