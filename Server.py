"""
server.py — JARVO web server.

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
import re
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

import executor  # noqa: F401  (registers tools with brain — import before brain.think)
import audio_io
import chat_store
import screen_tools
import stt
from brain import think
import tts
from main import detect_script, FALLBACKS

app = Flask(__name__, static_folder="static", static_url_path="")

# Optional shared-secret auth: set JARVO_TOKEN in .env to require it on
# every action endpoint (anything that can send WhatsApp/email/etc.).
# If JARVO_TOKEN is not set, auth is skipped (same behaviour as before --
# fine for a laptop-only demo, NOT fine once other devices join the WiFi).
JARVO_TOKEN = os.getenv("JARVO_TOKEN", "").strip()

# Endpoints that stay open even when JARVO_TOKEN is set (serving the page
# itself and a cheap liveness check -- neither can trigger an action).
_PUBLIC_PATHS = {"/", "/api/health"}


@app.before_request
def _check_auth():
    if not JARVO_TOKEN:
        return None  # auth disabled -- no token configured
    if request.method == "OPTIONS":
        return None  # let CORS preflight through
    if request.path in _PUBLIC_PATHS or request.path.startswith("/static"):
        return None
    supplied = request.headers.get("X-Auth-Token") or request.args.get("token", "")
    if supplied != JARVO_TOKEN:
        return jsonify({"error": "unauthorized -- missing or wrong token"}), 401
    return None


@app.after_request
def add_agent_cors(response):
    """Allow a separately hosted frontend to call this user's local agent."""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Private-Network", "true")
    return response

# Persistence: chat history + activity log live in chat_store.py (SQLite)
# now — per-session, so two devices never mix conversations and history
# survives server restarts. The session id comes from the browser via the
# X-Session-Id header; the server mints one on the first request and the
# client stores whatever the JSON response returns in "session".
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _get_session_id() -> str:
    """Validated session id from the X-Session-Id header, or a fresh one."""
    sid = (request.headers.get("X-Session-Id") or "").strip()
    if _SESSION_RE.match(sid):
        return sid
    return uuid.uuid4().hex  # 32 hex chars — matches _SESSION_RE


# Wrap brain.think so every tool run lands in the activity log (regardless
# of which code path — LLM call, fast-path, or capture safety net — ran it).
_think_inner = think


def think(text, session_id: str, hist=None):
    import brain as _brain
    orig_exec = _brain._executor

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
        chat_store.record_activity(session_id, name, detail, ok=not failed)
        return result

    try:
        _brain._executor = wrapped
        return _think_inner(text, hist if hist is not None else [])
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


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "agent": "jarvo", "service": "local"})


@app.route("/captures/<path:fname>")
def captures_file(fname):
    """Serve a screenshot/recording from the Pictures/JARVO folder."""
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

    session_id = _get_session_id()
    chat_store.touch_session(session_id)
    reply = _think_safely(text, session_id)
    _speak_async(reply)

    return jsonify({"ok": True, "user_text": text, "reply": reply, "session": session_id,
                    "speak_ms": _speak_ms(reply), "activity": chat_store.get_activity(session_id)})


@app.route("/api/text", methods=["POST"])
def api_text():
    """Typed-input path (no mic) — same pipeline minus STT."""
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Kuch likha nahi gaya."})

    session_id = _get_session_id()
    chat_store.touch_session(session_id)
    reply = _think_safely(text, session_id)
    _speak_async(reply)

    return jsonify({"ok": True, "user_text": text, "reply": reply, "session": session_id,
                    "speak_ms": _speak_ms(reply), "activity": chat_store.get_activity(session_id)})


@app.route("/api/history")
def api_history():
    """Stored conversation for this session (oldest first) — lets the UI
    restore the chat after a page reload or server restart."""
    session_id = _get_session_id()
    chat_store.touch_session(session_id)
    return jsonify({"ok": True, "session": session_id,
                    "messages": chat_store.get_history(session_id)})


@app.route("/api/history", methods=["DELETE"])
def api_history_delete():
    """"New chat": wipe this session's stored conversation and activity.
    Other sessions are untouched. The UI then mints a fresh session id."""
    session_id = _get_session_id()
    chat_store.clear_session(session_id)
    return jsonify({"ok": True, "session": session_id})


def _think_safely(text: str, session_id: str) -> str:
    history = chat_store.get_history(session_id)
    try:
        reply = think(text, session_id, history)
    except Exception as e:
        print(f"Error: {str(e)[:80]}")
        reply = FALLBACKS[len(history) % len(FALLBACKS)]

    chat_store.append_message(session_id, "user", text)
    chat_store.append_message(session_id, "assistant", reply)
    return reply


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print("=" * 52)
    print("  JARVO web server")
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
        host = os.getenv("JARVO_HOST", "127.0.0.1")
        app.run(host=host, port=port, debug=False)
    except OSError as e:
        if "10048" in str(e) or "in use" in str(e).lower() or "address" in str(e).lower():
            print(f"\n❌ Port {port} pehle se use mein hai.")
            print("   Fix 1: Purani JARVO server window band karein (Ctrl+C us window mein).")
            print(f"   Fix 2: Doosra port:  venv\\Scripts\\python Server.py {port + 1}")
        else:
            raise