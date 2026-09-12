"""
server.py — SAATHI web server.

Serves a polished browser-based chat UI (static/index.html) and exposes
the existing voice pipeline (audio_io -> stt -> brain -> executor -> tts)
over simple HTTP endpoints, so the whole thing looks and feels like a real
app instead of a command-prompt window.

IMPORTANT: the microphone recording and TTS playback happen on THIS laptop
(same as before) — a phone opening this over WiFi is remote-controlling the
laptop's mic/speakers, not using its own. That's expected for a hackathon
local-agent demo; see the project docs for the deployment note.

Run:
    venv\\Scripts\\python server.py

Then open in a browser:
    http://localhost:5000              (on this laptop)
    http://<this-laptop's-LAN-IP>:5000 (from a phone/other device on same WiFi)
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import threading

import time

from flask import Flask, jsonify, request, send_from_directory

import executor  # noqa: F401  (registers tools with brain — import before brain.think)
import audio_io
import screen_tools
import stt
from brain import think
import tts
from main import detect_script, FALLBACKS

app = Flask(__name__, static_folder="static", static_url_path="")

history = []  # simple in-memory chat history (single-user demo)
activity_log = []  # last tool runs, newest last: {"tool", "detail", "ok", "t"}


def _record_activity(tool: str, detail: str = "", ok: bool = True):
    """Track tool runs so the UI can show a live agent-activity strip."""
    activity_log.append({
        "tool": tool, "detail": detail[:60], "ok": ok,
        "t": int(time.time()),
    })
    del activity_log[:-12]


# Wrap brain.think so every tool run lands in the activity log (regardless
# of which code path — LLM call, fast-path, or capture safety net — ran it).
_think_inner = think


def think(text, hist=None):
    import brain as _brain
    orig_exec = _brain._executor
    log = _record_activity

    def wrapped(name, args):
        result = orig_exec(name, args)
        failed = any(m in (result or "").lower()
                     for m in ("error", "failed", "nahi mili", "nahi mila", "could not"))
        detail = (result or "")[:60]
        if name == "send_whatsapp":
            detail = f"{args.get('contact', '')}: {args.get('message', '')[:40]}"
        elif name == "send_email":
            detail = f"to {args.get('to', '')}"
        elif name == "open_app":
            detail = args.get("app_name", "")
        elif name == "web_search":
            detail = args.get("query", "")
        log(name, detail, ok=not failed)
        return result

    try:
        _brain._executor = wrapped
        return _think_inner(text, hist if hist is not None else history)
    finally:
        _brain._executor = orig_exec


def _speak_async(reply: str):
    """TTS in a background thread so the web UI gets the reply instantly and
    can animate the 'speaking' state in sync with the actual audio."""
    threading.Thread(target=tts.speak, args=(reply, detect_script(reply)), daemon=True).start()


def _speak_ms(reply: str) -> int:
    """Rough duration of the spoken reply in ms (for the UI animation)."""
    return min(12000, max(1200, len(reply.split()) * 380 + 600))


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/captures/<path:fname>")
def captures_file(fname):
    """Serve a screenshot/recording from the Pictures/SAATHI folder."""
    return send_from_directory(screen_tools.SHOTS_DIR, fname)


@app.route("/api/captures")
def api_captures():
    """List screenshots + recordings, newest first."""
    items = []
    try:
        for f in os.listdir(screen_tools.SHOTS_DIR):
            p = os.path.join(screen_tools.SHOTS_DIR, f)
            if not os.path.isfile(p):
                continue
            ext = f.rsplit(".", 1)[-1].lower()
            kind = "video" if ext in ("mp4", "webm") else ("image" if ext in ("png", "jpg") else None)
            if not kind:
                continue
            items.append({
                "name": f,
                "kind": kind,
                "size_kb": round(os.path.getsize(p) / 1024),
                "mtime": int(os.path.getmtime(p)),
            })
    except FileNotFoundError:
        pass
    items.sort(key=lambda x: -x["mtime"])
    return jsonify({"ok": True, "items": items})


@app.route("/api/contacts")
def api_contacts():
    """Known contacts (name + phone) for the sidebar Contacts view."""
    try:
        from whatsapp_bot import _load_contacts
        rows = [
            {"name": n, "phone": v.get("phone") or ""}
            for n, v in _load_contacts().items() if not n.startswith("_")
        ]
        rows.sort(key=lambda r: r["name"].lower())
        return jsonify({"ok": True, "contacts": rows})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:80]})


@app.route("/api/listen", methods=["POST"])
def api_listen():
    """Records from the mic, transcribes, thinks, speaks. Returns JSON."""
    try:
        audio = audio_io.record_until_silence()
    except Exception as e:
        # Mic busy (dusri stream/tab khuli hai) ya device error — clear message
        # instead of a 500 that would show up as a generic connection error.
        print(f"⚠  Mic capture failed: {type(e).__name__}")
        return jsonify({"ok": False, "error": "Mic busy hai — dusri stream band karke dobara bolein."})
    if audio is None:
        return jsonify({"ok": False, "error": "Kuch sunai nahi diya. Dobara koshish karen."})

    text, lang = stt.transcribe(audio)
    if not text:
        return jsonify({"ok": False, "error": "Samajh nahi aaya. Dobara bolein."})

    reply = _think_safely(text)
    _speak_async(reply)

    return jsonify({"ok": True, "user_text": text, "reply": reply,
                    "speak_ms": _speak_ms(reply), "activity": activity_log[-6:]})


@app.route("/api/text", methods=["POST"])
def api_text():
    """Typed-input path (no mic) — same pipeline minus STT."""
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Kuch likha nahi gaya."})

    reply = _think_safely(text)
    _speak_async(reply)

    return jsonify({"ok": True, "user_text": text, "reply": reply,
                    "speak_ms": _speak_ms(reply), "activity": activity_log[-6:]})


def _think_safely(text: str) -> str:
    global history
    try:
        reply = think(text, history)
    except Exception as e:
        print(f"Error: {str(e)[:80]}")
        reply = FALLBACKS[len(history) % len(FALLBACKS)]

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    del history[:-10]
    return reply


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print("=" * 52)
    print("  SAATHI web server")
    print("=" * 52)
    print("⏳ Modules load ho rahe hain (10-20s lag sakta hai)...")

    # WhatsApp background pre-load (jaise main.py karta hai) — voice se
    # message bhejne ka pehla command fast ho jata hai.
    try:
        import whatsapp_bot
        whatsapp_bot.warm_up(background=True)
    except Exception:
        pass

    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except OSError as e:
        if "10048" in str(e) or "in use" in str(e).lower() or "address" in str(e).lower():
            print(f"\n❌ Port {port} pehle se use mein hai.")
            print("   Fix 1: Purani SAATHI server window band karein (Ctrl+C us window mein).")
            print(f"   Fix 2: Doosra port:  venv\\Scripts\\python Server.py {port + 1}")
        else:
            raise