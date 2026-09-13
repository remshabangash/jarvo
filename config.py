import os

from dotenv import load_dotenv

load_dotenv()

# LLM (Groq free tier) — 20b primary: flawless tool-JSON + fastest; 120b fallback
GROQ_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# STT (Groq-hosted Whisper; no local download needed).
# IMPORTANT: uses its own API key (GROQ_API_KEY_STT), separate from the LLM
# key above. Whisper (STT) and the brain (LLM) used to share ONE Groq key —
# every voice turn could burn 2-4 requests total (STT auto-detect + retry,
# then LLM + fallback), so the two features constantly rate-limited each
# other. Two free-tier keys = two separate quota buckets.
# If GROQ_API_KEY_STT is not set in .env, it safely falls back to the main
# key (so nothing breaks if you haven't made a second key yet).
GROQ_API_KEY_STT = os.getenv("GROQ_API_KEY_STT") or GROQ_API_KEY
WHISPER_MODEL = "whisper-large-v3"

# TTS voices per language (edge-tts)
TTS_VOICES = {
    "ur": "ur-PK-AsadNeural",        # Urdu (Pakistan)
    "en": "en-US-AndrewNeural",      # English
    "ps": "ps-AF-GulNawazNeural",    # Pashto (native voice)
}

# Audio capture
# Optional mic device override — index from mic_test.py output.
# Windows often defaults to a dead/external mic endpoint (e.g. an unplugged
# jack); pin the working device so listening always uses the live mic.
JARVO_MIC_DEVICE = os.getenv("JARVO_MIC_DEVICE")
if JARVO_MIC_DEVICE is not None and JARVO_MIC_DEVICE.strip().isdigit():
    JARVO_MIC_DEVICE = int(JARVO_MIC_DEVICE.strip())
else:
    JARVO_MIC_DEVICE = None  # None = OS default

SAMPLE_RATE = 16000
SILENCE_RMS = 250          # fallback floor; real threshold is calibrated from ambient noise
SILENCE_SECONDS = 1.2      # end-of-turn silence — was 0.9s, cutting off mid-sentence
                           # on natural Urdu speech pauses; 1.2s gives more breathing room
MAX_RECORD_SECONDS = 20.0  # hard cap per utterance — was 12s, too short for dictating
                           # a full WhatsApp message or a longer question
MIN_SPEECH_SECONDS = 0.35  # shorter than this = noise, ignore — was 0.5s, which was
                           # dropping short valid replies like "haan" / "yes" / "ok"
AMBIENT_CALIB_SECONDS = 0.7
THRESHOLD_FLOOR = 220

# Playback
MP3_PATH = os.path.join(os.path.dirname(__file__), "reply.mp3")