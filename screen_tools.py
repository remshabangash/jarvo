"""Screen capture tools — voice-controlled screenshots & screen recording.

- take_screenshot(): PNG of the primary monitor -> captures/screenshot_*.png
- start_recording(): MP4 screen recording (background thread, ~15 fps)
  -> captures/recording_*.mp4
- stop_recording(): stops the active recording, returns where it saved

Recording auto-stops after MAX_RECORDING_SECONDS (safety net) — audio
"stop recording" bolna normal tareeqa hai.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from datetime import datetime

import config

# Save to the laptop's standard Pictures library (easy to find in File
# Explorer sidebar), NOT inside the project folder.
SHOTS_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "JARVO")
os.makedirs(SHOTS_DIR, exist_ok=True)


def _save_path(prefix: str, ext: str) -> str:
    """Timestamped save path. Re-creates the folder (it can be deleted by
    cleanup tools mid-run) and falls back to TEMP so a capture NEVER fails."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = SHOTS_DIR
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = os.path.join(tempfile.gettempdir(), "JARVO_captures")
        os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{prefix}_{stamp}.{ext}")


MAX_RECORDING_SECONDS = 300  # safety: 5 min cap per recording
FPS = 15

# Active recording state (single recording at a time)
_rec: dict | None = None
_lock = threading.Lock()


def _primary_monitor(sct):
    """mss monitor dict for the PRIMARY screen (index 1 = primary; 0 = all)."""
    return sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]


def take_screenshot() -> str:
    """Capture the primary monitor as PNG. Returns the saved path."""
    import mss
    import mss.tools

    path = _save_path("screenshot", "png")
    with mss.mss() as sct:
        shot = sct.grab(_primary_monitor(sct))
        mss.tools.to_png(shot.rgb, shot.size, output=path)
    return path


def _record_job(path: str, stop_event: threading.Event):
    """Background loop: grab frames -> mp4 via OpenCV VideoWriter.

    Frame pacing: a full-screen grab can take longer than one 1/FPS tick, so
    instead of writing one frame per grab (which would make playback too
    fast), we write on every tick and reuse the latest grabbed frame when a
    grab is slow. Duration then matches real time exactly.
    """
    import mss
    import numpy as np
    import cv2

    interval = 1.0 / FPS
    writer = None
    last_frame = None
    started = time.time()
    try:
        with mss.mss() as sct:
            mon = _primary_monitor(sct)
            next_tick = started + interval
            while not stop_event.is_set() and (time.time() - started) < MAX_RECORDING_SECONDS:
                try:
                    frame = np.ascontiguousarray(np.array(sct.grab(mon))[:, :, :3])  # BGRA->BGR
                    last_frame = frame
                except Exception:
                    pass  # keep last frame on transient grab errors
                if writer is None and last_frame is not None:
                    h, w = last_frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(path, fourcc, FPS, (w, h))
                if writer is not None:
                    # write one frame for every tick that has passed
                    while time.time() >= next_tick:
                        writer.write(last_frame)
                        next_tick += interval
                time.sleep(0.002)
    except Exception as e:
        print(f"⚠  Recorder error: {type(e).__name__}: {str(e)[:80]}")
    finally:
        if writer is not None:
            writer.release()


def start_recording() -> str:
    """Start a background screen recording. Returns the target mp4 path."""
    global _rec
    with _lock:
        if _rec is not None and _rec["thread"].is_alive():
            return f"Error: recording pehle se chal rahi hai. 'stop recording' bolein."
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _save_path("recording", "mp4")
        stop = threading.Event()
        t = threading.Thread(target=_record_job, args=(path, stop), daemon=True)
        t.start()
        _rec = {"thread": t, "stop": stop, "path": path, "start": time.time()}
        return path


def stop_recording() -> str:
    """Stop the active recording. Returns a speakable result."""
    global _rec
    with _lock:
        if _rec is None or not _rec["thread"].is_alive():
            _rec = None
            return "Error: abhi koi recording chal nahi rahi."
        dur = time.time() - _rec["start"]
        path = _rec["path"]
        _rec["stop"].set()
        thread = _rec["thread"]
        _rec = None
    thread.join(timeout=10)
    mins = int(dur // 60)
    secs = int(dur % 60)
    return f"Recording saved: {path} ({mins}m {secs:02d}s)"


def is_recording() -> bool:
    return _rec is not None and _rec["thread"].is_alive()