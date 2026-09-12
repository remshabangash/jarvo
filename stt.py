"""Speech-to-Text using Groq-hosted Whisper (free, no local model download).

Whisper auto-detect often mislabels Urdu as Hindi (Devanagari output) and
Pashto as Arabic. We do an auto pass first, then a forced-language retry
when the detected language looks like a misfire.
"""
import json
import os
import tempfile
import time

import numpy as np
from groq import Groq

import config

_client = Groq(api_key=config.GROQ_API_KEY_STT)


def _load_contact_names(max_chars: int = 300) -> str:
    """Comma-separated contact names to bias Whisper's spelling of names
    (e.g. hearing "Asif" correctly instead of "Asifa"). Capped in total
    characters (not just count) so the full prompt never exceeds Groq's
    896-character limit on the Whisper `prompt` field."""
    try:
        path = os.path.join(os.path.dirname(__file__), "contacts.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        names = [k for k in data.keys() if not k.startswith("_")]
        out = []
        total = 0
        for n in names:
            add = len(n) + 2  # ", "
            if total + add > max_chars:
                break
            out.append(n)
            total += add
        return ", ".join(out)
    except Exception:
        return ""


_CONTACT_NAMES = _load_contact_names()

# Whisper language name -> our 2-letter codes
_NAME_TO_CODE = {
    "english": "en",
    "urdu": "ur",
    "hindi": "hi",
    "arabic": "ar",
}

# Misfire -> forced retry language (Whisper sometimes mislabels Urdu as
# Hindi/Devanagari, or as Arabic — always remap back to Urdu, we only
# support Urdu + English now).
_REMAP = {"hi": "ur", "ar": "ur"}

# Whisper frequently mis-hears English loanwords spoken with a Pakistani/desi
# accent as garbled Urdu/Arabic-script variants. We normalize the transcript
# AFTER Whisper returns it — much more reliable than hoping the model gets it
# right, and works regardless of which of the 3 languages was spoken.
# Add more entries here any time you notice a new misheard variant in logs.
_WORD_FIXES = [
    # WhatsApp — Whisper has heard all of these for the same word
    (r"ویڈس\s*ایپ", "WhatsApp"),
    (r"ورسیپ", "WhatsApp"),
    (r"ویٹس\s*ایپ", "WhatsApp"),
    (r"واٹس\s*ایپ", "WhatsApp"),
    (r"وٹس\s*ایپ", "WhatsApp"),
    (r"whats\s*app", "WhatsApp"),
    # More Roman-Urdu/English phonetic mishears of "WhatsApp" seen in logs —
    # Whisper sometimes drops the "wh" or "t" sound entirely, especially on
    # a Pakistani accent, and outputs something short like "Asep"/"Asap".
    (r"\bas[ae]p\b", "WhatsApp"),
    (r"\bwasap\b", "WhatsApp"),
    (r"\bwazap\b", "WhatsApp"),
    (r"\bhotsapp\b", "WhatsApp"),
    # YouTube
    (r"یوٹیوب", "YouTube"),
    (r"یو ٹیوب", "YouTube"),
    # Chrome / browser
    (r"براؤزر", "browser"),
    (r"کروم", "Chrome"),
]

# Bias decode toward Pakistani Urdu + English + the correct spelling of
# common English loanwords (WhatsApp, YouTube) that get garbled otherwise.
_PROMPT = "پاکستانی اردو یا انگریزی میں گفتگو۔ WhatsApp, YouTube, Chrome. Pakistani Urdu or English conversation."

# When True, Urdu speech is transcribed phonetically in Latin letters
# ("Roman Urdu", e.g. "kya hal hai") instead of Urdu (Perso-Arabic) script.
# Whisper does this reliably if we force language="en" — it then writes
# non-English speech out phonetically using Latin letters instead of
# attempting real translation or native script.
ROMAN_URDU_MODE = True

# Prompt used only when ROMAN_URDU_MODE is on — nudges Whisper to keep
# writing Latin letters instead of switching to Urdu script mid-way, and
# gives it the correct spelling of the user's contacts so names aren't
# misheard (e.g. "Asif" heard as "Asifa").
_ROMAN_PROMPT = (
    "Roman Urdu likha hua matn, jaise: kya hal hai, tum kahan ho, "
    "mujhe WhatsApp pe message bhejo. Likha jaye Latin/Roman letters mein, "
    "Urdu script mein nahi. "
    + (f"Contact names jo sunai de saktay hain: {_CONTACT_NAMES}." if _CONTACT_NAMES else "")
)[:890]  # hard safety clamp — Groq rejects prompts over 896 chars


def _call_wav(path: str, language: str | None = None):
    """One Whisper call with 429 backoff (free tier RPM hit in live demos)."""
    # Roman Urdu mode: force language="en" so Whisper writes Urdu speech
    # phonetically in Latin letters instead of switching to Urdu script.
    call_language = language
    prompt = _PROMPT
    if ROMAN_URDU_MODE:
        if language in ("ur", "hi", "ar") or language is None:
            call_language = "en"
            prompt = _ROMAN_PROMPT

    for attempt in range(3):
        try:
            with open(path, "rb") as f:
                resp = _client.audio.transcriptions.create(
                    model=config.WHISPER_MODEL,
                    file=(os.path.basename(path), f),
                    response_format="verbose_json",
                    prompt=prompt,
                    **({"language": call_language} if call_language else {}),
                )
            break
        except Exception as e:
            msg = str(e)
            if ("429" in msg or "rate" in msg.lower()) and attempt < 2:
                print("⏳ STT rate limit — 4s ruk kar dobara...")
                time.sleep(4.0)
                continue
            raise
    text = (resp.text or "").strip()
    name = (getattr(resp, "language", "") or "").lower()
    code = _NAME_TO_CODE.get(name, name[:2] if name else "")
    return text, code


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    import io
    import wave

    audio = np.asarray(audio, dtype=np.int16)  # guarantee int16 bytes
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(config.SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def _normalize(text: str) -> str:
    """Fix commonly-misheard English loanwords after Whisper transcribes."""
    import re
    for pattern, replacement in _WORD_FIXES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def transcribe(audio) -> tuple[str, str]:
    """Transcribe int16 audio array. Returns (text, language_code)."""
    text, lang = _transcribe_raw(audio)
    return _normalize(text), lang


def _transcribe_raw(audio) -> tuple[str, str]:
    wav = _to_wav_bytes(audio)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "speech.wav")
        with open(path, "wb") as f:
            f.write(wav)

        # Pass 1: auto-detect
        text, lang = _call_wav(path)
        if not text:
            # Empty: try forcing each language once
            for forced in ("ur", "en"):
                text, lang = _call_wav(path, forced)
                if text:
                    break
            return text, lang

        # Pass 2: remap known misfires (Hindi->Urdu, Arabic->Pashto)
        if lang in _REMAP:
            text2, lang2 = _call_wav(path, _REMAP[lang])
            if text2:
                return text2, lang2

        # Pass 2b: totally unknown language -> force English retry
        if lang not in ("en", "ur", "ps"):
            text3, _ = _call_wav(path, "en")
            if text3:
                return text3, "en"

        return text, lang