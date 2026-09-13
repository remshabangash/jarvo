# JARVO — Multilingual Voice Assistant

[![CI](https://github.com/remshabangash/jarvo/actions/workflows/ci.yml/badge.svg)](https://github.com/remshabangash/jarvo/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![Tests](https://img.shields.io/badge/tests-95%20passing-brightgreen)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

Speak in **Urdu, English, or Pashto** — JARVO listens, understands free-form
intent, and actually *does things* on your computer: opens apps, sends
WhatsApp messages and emails, takes screenshots, records the screen, and
drives a browser. 100% free stack, no paid APIs.

```
🎤 Mic → 📝 Whisper STT (Groq) → 🧠 LLM Brain (Groq, tool-use) → ⚙️ Executor → 🔊 TTS (edge-tts)
```

## Features

| | Say it like this | What happens |
|---|---|---|
| 🚀 Open anything | *"Notepad khol do"*, *"Open YouTube"* | Any installed app, UWP/Store app, or website — resolved live from the Start Menu (no fixed command list) |
| 💬 WhatsApp | *"Ahmed ko hello bhejo"* | Real send through a pre-loaded, persistent WhatsApp Web session with header + send verification |
| 📧 Email | *"Sara ko email bhejo"* | Gmail SMTP with contact-name resolution |
| 🌐 Controlled browser | *"...is par click karo, neeche scroll karo"* | Follow-up commands act on the same Selenium-driven page across turns |
| 📸 Screen capture | *"screenshot le lo"*, *"recording shuru karo"* | PNG + MP4 (real-time paced), saved to `Pictures/JARVO` |
| 🗂️ Save contacts by voice | *"Ali ka number save karo 9230..."* | Confirms digits back, then writes WhatsApp/email contacts atomically |
| 💾 Remembers the conversation | — | Chat history persists in SQLite per device/session — survives restarts and reloads |
| 🌍 Three languages | Urdu / English / Pashto | Roman-Urdu transcription handling, native Pashto TTS voice, per-reply voice selection |

Every destructive action (sends, saves) goes through a spoken **confirmation
step** — nothing goes out on a single misheard word.

## Quick Start

```bash
# 1. Environment
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# 2. API keys — copy the template, add your Groq keys
copy .env.example .env        # then edit .env

# 3. Personal data — templates only; fill with YOUR contacts
copy contacts.example.json contacts.json
copy email_contacts.example.json email_contacts.json

# 4. WhatsApp one-time login (QR scan, session is saved)
venv\Scripts\python whatsapp_login.py

# 5. Run!
venv\Scripts\python main.py          # voice mode
venv\Scripts\python main.py --text   # keyboard mode
venv\Scripts\python Server.py        # web UI → http://localhost:5000
```

Keys are free: [console.groq.com/keys](https://console.groq.com/keys) (LLM +
STT). Optional: Gmail **App Password** for email, `JARVO_TOKEN` for web
authentication.

## How it stays fast (demo secrets)

- **WhatsApp pre-loads in the background at startup** — the first voice
  command doesn't pay the 25–40s web-app cold load (~1–2s re-sends).
- In-app search opens chats; slow `wa.me` deep-links are the last resort.
- Whisper misfires (Urdu→Hindi/Arabic) are auto-remapped; misheard
  WhatsApp/YouTube/Chrome words are post-corrected.
- LLM: `gpt-oss-20b` primary (fast, reliable tool-JSON), `120b` fallback on
  rate limits. Tool calls carry their own spoken reply — no extra round-trip.

## Architecture

```
main.py / Server.py / gui.py      ← entry points (voice / web / windowed)
        │
   audio_io.py                    mic capture, ambient calibration, VAD
   stt.py                         Groq Whisper + language retry + word fixes
   brain.py                       LLM tool-use, confirmation state machine
   executor.py                    dispatch: tools → workers
   ├── app_resolver/              cross-platform app launching (win/macos/linux)
   ├── whatsapp_bot.py            Selenium WhatsApp Web (persistent session)
   ├── email_sender.py            Gmail SMTP + voice-saved contacts
   ├── screen_tools.py            screenshots + MP4 recording
   ├── browser_bot.py             controllable browser (click/scroll/type)
   └── chat_store.py              SQLite: sessions, history, activity
static/index.html                 web UI (auth-aware, history restore)
tests/                            95 offline tests (mocked LLM, no API keys)
```

## Testing & CI

Every push runs [GitHub Actions CI](.github/workflows/ci.yml):
**compile checks on all 22 modules + 95 offline unit tests** (brain pipeline
with a fake Groq client, WhatsApp/email confirmation state machines, OS
resolvers, STT normalization, SQLite store) — fully mocked, no API keys
needed. Run locally:

```bash
venv\Scripts\python -m pytest tests/ -v
```

## Security notes

- The web server binds **127.0.0.1 by default** — only this laptop can reach it.
  To serve other devices on your WiFi, set `JARVO_HOST=0.0.0.0` and **set
  `JARVO_TOKEN`** in `.env`; the web UI will prompt for the token once and
  sign every request.
- Personal files (`.env`, `contacts.json`, `email_contacts.json`, `jarvo.db`)
  are gitignored — templates live in the repo, real data stays on your machine.
- Voice-saved contacts and all sends require spoken confirmation first.

## Known limitations

- WhatsApp automation depends on WhatsApp Web's DOM — UI changes upstream can
  need selector updates (`wa_doctor.py` diagnoses).
- STT/LLM are cloud (Groq) — a network outage stops new commands (voice modes
  degrade gracefully with spoken fallbacks).
- Screen recording caps at 5 minutes (safety), 15 fps.
