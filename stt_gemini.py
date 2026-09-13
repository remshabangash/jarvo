"""Speech-to-Text via Google's Gemini 3.5 Transcribe (optional Whisper upgrade).

Why this exists: Whisper auto-detect often mislabels Urdu/Pashto and garbles
desi-accented English loanwords. Gemini 3.5 Transcribe auto-detects 85+
languages and handles accents better (2.6% WER on their benchmarks).

API notes (probed live against gemini-3.5-transcribe):
- The model accepts ONLY audio/text parts. `system_instruction` is rejected
  with 400 "Developer instruction is not enabled for this model". That is
  fine for us: a transcription-only model has no chat behavior to "clean
  up" with, so output is verbatim by construction.
- Transcripts come back in parts[].audioTranscription.text (NOT parts[].text
  like a regular generateContent response — we support both, future-proof).
- No language metadata is returned today; voice selection happens later via
  script detection on the REPLY text, so nothing depends on it.

This module is stdlib-only (urllib + base64) so requirements.txt stays clean.

Dispatch lives in stt.transcribe(): STT_PROVIDER="auto" prefers this module
when GEMINI_API_KEY is set and falls back to Whisper on any error, so a
network/Google outage never takes the assistant down.
"""
import base64
import json
import time
import urllib.error
import urllib.request

import config

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


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
    """True when a Gemini key is configured."""
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
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected Gemini response shape: {e}") from e

    # Transcribe models put text under parts[].audioTranscription.text;
    # plain generateContent uses parts[].text. Accept both.
    text = ""
    for p in parts:
        if not isinstance(p, dict):
            continue
        chunk = (p.get("audioTranscription") or {}).get("text") or p.get("text") or ""
        text += chunk
    text = text.strip()
    if not text:
        raise RuntimeError("Gemini returned an empty transcript")

    return text, _extract_lang(data)


def _extract_lang(data: dict) -> str:
    """Best-effort 2-letter language code; "en" when absent.

    The transcribe models return no language metadata today — this value is
    informational only (TTS voice is chosen later from the reply's script).
    """
    try:
        result = data["candidates"][0].get("speechResult", {}).get("languageCode", "")
        code = result.split("-")[0].lower()
        if code:
            return code
    except (KeyError, AttributeError, TypeError):
        pass
    return "en"
