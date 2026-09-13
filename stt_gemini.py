"""Speech-to-Text via Google's Gemini 3.5 Transcribe (optional Whisper upgrade).

Why this exists: Whisper auto-detect often mislabels Urdu/Pashto and garbles
desi-accented English loanwords. Gemini 3.5 Transcribe auto-detects 85+
languages, handles accents better, and supports custom vocabulary hints.

API shape (non-streaming transcription):
    POST https://generativelanguage.googleapis.com/v1beta/models/
         {model}:generateContent?key=API_KEY
    body: inline_data {mime_type "audio/wav;rate=16000", data: base64 wav}
          + system_instruction telling it to keep the user's EXACT words.

This module is stdlib-only (urllib + base64) so requirements.txt stays clean.

Dispatch lives in stt.transcribe(): STT_PROVIDER="auto" prefers this module
when GEMINI_API_KEY is set and falls back to Whisper on any error, so a
network/Google outage never takes the assistant down.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

import config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# When True, Urdu speech comes back in Latin letters ("kya hal hai") instead
# of Urdu script — mirrors stt.ROMAN_URDU_MODE so the brain's Roman-Urdu
# handling behaves identically on both engines.
ROMAN_URDU_MODE = True

# Custom vocabulary bias: names the user actually has, so "Asif" isn't
# transcribed as "Asifa". Capped like Whisper's prompt to keep requests small.
_VOCAB_HINT = ""
try:
    with open(os.path.join(os.path.dirname(__file__), "contacts.json"), encoding="utf-8") as _f:
        _names = [k for k in json.load(_f) if not k.startswith("_")]
        _VOCAB_HINT = ", ".join(_names)[:200]
except Exception:
    pass


def _build_instruction() -> str:
    lang = (
        "Roman Urdu (Latin letters, NOT Urdu script) or English, as spoken."
        if ROMAN_URDU_MODE
        else "Urdu, English or Pashto, exactly as spoken."
    )
    instr = (
        "Transcribe the audio verbatim. Language: " + lang + "\n"
        "Rules:\n"
        "1. NEVER clean up, translate or rephrase — keep the speaker's EXACT "
        "words and word order (fillers included). This is a command assistant; "
        "changing words changes the command.\n"
        "2. Keep English loanwords in English: WhatsApp, YouTube, Chrome, "
        "Notepad, email.\n"
        "3. Output ONLY the transcript text, no labels or commentary."
    )
    if _VOCAB_HINT:
        instr += "\nKnown contact names (use this exact spelling): " + _VOCAB_HINT
    return instr


def _post(url: str, body: dict, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def available() -> bool:
    """True when a Gemini key is configured (import-time _API_KEY check)."""
    return bool(getattr(config, "GEMINI_API_KEY", None))


def transcribe_wav_bytes(wav: bytes) -> tuple[str, str]:
    """Transcribe WAV bytes via Gemini. Returns (text, 2-letter language code).

    Raises on any API failure — the caller (stt.transcribe) owns the
    Whisper fallback, so this module stays simple.
    """
    key = config.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    body = {
        "system_instruction": {"parts": [{"text": _build_instruction()}]},
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/wav;rate=16000",
                            "data": base64.b64encode(wav).decode("ascii"),
                        }
                    }
                ]
            }
        ],
    }

    last_err: Exception | None = None
    for attempt in range(3):  # brief backoff for transient 429/5xx
        try:
            data = _post(API_URL.format(model=config.GEMINI_STT_MODEL, key=key), body)
            break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
    else:  # pragma: no cover — loop only exits via break or raise
        raise last_err  # type: ignore[misc]

    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected Gemini response shape: {e}") from e
    if not text:
        raise RuntimeError("Gemini returned an empty transcript")

    return text, _extract_lang(data)


def _extract_lang(data: dict) -> str:
    """Best-effort 2-letter language code from Gemini's response metadata."""
    try:
        # NLS (natural language understanding) result, e.g. "ur-PK", "en-US"
        result = data["candidates"][0].get("speechResult", {}).get("languageCode", "")
        code = result.split("-")[0].lower()
        if code:
            return code
    except (KeyError, AttributeError, TypeError):
        pass
    # Fall back to the model's own reported thinking language, else "en" —
    # voice selection happens later via script detection on the reply text.
    return "en"
