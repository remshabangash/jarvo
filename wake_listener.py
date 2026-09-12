"""wake_listener.py — background wake-word service for SAATHI.

Run this at Windows startup (see setup_autostart.bat). It sits quietly in
the background, listens to short bursts of audio, and only when it hears
something matching "SAATHI" does it:
  1. Start Server.py (if it isn't already running on port 5000), and
  2. Open the browser to http://127.0.0.1:5000

It does NOT stream audio to the cloud constantly — audio_io.record_until_silence
only returns a clip when the mic actually picks up speech above the ambient
threshold, so during silence there is no network call and no cost. Only when
a clip is captured do we send that one short clip to Groq Whisper for
transcription and check it for the wake word.
"""
import difflib
import os
import socket
import subprocess
import sys
import time
import webbrowser

import audio_io
import stt

PORT = 5000
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Common ways Whisper mishears "SAATHI" when spoken casually / with an accent.
_WAKE_VARIANTS = [
    "saathi", "sathi", "saathi", "sathi", "sathee", "saathy", "saati", "saathi",
    "sarty", "sarthy", "saathi", "sathi", "ps", "ps apps", "sp", "swati",
    "psi", "sps", "sathi ho", "sat hi", "such he", "su hi",
]


def _heard_wake_word(text: str) -> bool:
    words = text.lower().replace(",", " ").replace(".", " ").split()
    # check consecutive 1-2 word windows against the variant list
    candidates = words + [
        f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)
    ]
    for cand in candidates:
        for variant in _WAKE_VARIANTS:
            if difflib.SequenceMatcher(None, cand, variant).ratio() > 0.72:
                return True
    return False


def _server_already_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _launch_server_and_browser():
    if not _server_already_running():
        print("🚀 Starting SAATHI server...")
        # Use the same interpreter that's running this script (so it picks
        # up the active venv automatically).
        subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_DIR, "Server.py")],
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        # Give Flask a few seconds to finish loading modules before we
        # point a browser at it.
        for _ in range(20):
            time.sleep(0.5)
            if _server_already_running():
                break
    webbrowser.open(f"http://127.0.0.1:{PORT}")
    print("✅ SAATHI is open.")


def main():
    print("👂 SAATHI wake-word listener running in the background.")
    print('   Say "Hi SAATHI" any time to open the assistant.')
    while True:
        try:
            audio = audio_io.record_until_silence(max_wait_for_speech=4.0)
            if audio is None:
                continue
            text, _lang = stt.transcribe(audio)
            if not text:
                continue
            if _heard_wake_word(text):
                print(f'🎙  Wake word detected ("{text}") — launching SAATHI.')
                _launch_server_and_browser()
                # Short cooldown so it doesn't immediately re-trigger on the
                # tail end of the same phrase or on the browser's own sounds.
                time.sleep(3.0)
        except KeyboardInterrupt:
            print("\n👋 Wake listener stopped.")
            break
        except Exception as e:
            print(f"⚠  Wake listener error (continuing): {e}")
            time.sleep(1.0)


if __name__ == "__main__":
    main()