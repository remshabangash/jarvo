# SAATHI — Multilingual Voice Assistant

Urdu / English / Pashto voice assistant — Mic → Whisper STT (Groq) → LLM Brain (Groq, tool-use) → Task Executor → TTS (edge-tts). 100% free stack.

## Setup (one-time)

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

`.env` mein Groq key (`.env.example` copy kar ke shuru karein):

```
GROQ_API_KEY=gsk_...
```

Personal data files (gitignored — repo mein template versions hain):

```bash
copy contacts.example.json contacts.json          # WhatsApp contacts + numbers
copy email_contacts.example.json email_contacts.json  # Email contacts
```
(In dono files mein apne REAL contacts bhar dein — ye sirf aapke laptop par rehti hain.)

## Run

```bash
venv\Scripts\python main.py
```

Bol kar baat karein. `quit` bolein ya Ctrl+C dabaein.

## Kya kaam kar sakta hai

- **App kholna** — "Notepad khol do", "Open Chrome"
- **Web search** — "Pakistan ka score batao"
- **WhatsApp** — "Ahmed ko hello bhejo" (pehli baar: Edge profile login, details neeche)
- **Screenshot** — "screenshot le lo", "screen ki photo lo" → `captures/` mein PNG
- **Screen recording** — "screen recording shuru karo" ... "recording band karo" → MP4
- **General baat-cheet** — koi bhi sawal, kisi bhi zaban mein

## WhatsApp ka pehla setup (demo se pehle ek baar)

```bash
venv\Scripts\python whatsapp_login.py
```

- WhatsApp Web QR scan karein — session `~/saathi_edge_profile` mein save hota hai
- Iske baad voice se message bhejna kaam karega bina QR ke

### Speed ka raaz (kyun ab ye fast hai)

- **Startup par WhatsApp background mein pre-load** hota hai — jab tak aap pehla
  command bolte ho, session already ready (warna 25–40s cold load lagta)
- **Deep-link navigation sirf last resort** — har `wa.me` navigation poori web app
  ko dobara bootstrap karti hai (25–40s). Normal sends in-app search se chat kholte
  hain: **~9s pehli baar, ~1–2s agli baar same chat** (composer direct)
- Har chat kholne se pehle **header verify** hota hai — ghalat chat mein type nahi hoga
- Har send ke baad **verify** hota hai ke message pane mein actually aaya —
  warna saaf error bolti hai (screenshot `wa_error.png` mein)

## Architecture / Files

| File | Kaam |
|---|---|
| `main.py` | Main loop: mic → STT → brain → executor → TTS |
| `audio_io.py` | Mic recording (silence-detection) |
| `stt.py` | Groq Whisper (cloud) + language retry logic |
| `brain.py` | Groq LLM + tool definitions |
| `executor.py` | open_app / web_search / whatsapp / screenshot / recording dispatch |
| `screen_tools.py` | Screenshot (mss) + MP4 screen recording (OpenCV, background thread) |
| `whatsapp_bot.py` | Selenium WhatsApp Web automation (persistent + pre-loaded Edge session) |
| `wa_doctor.py` | WhatsApp diagnosis: `venv\Scripts\python wa_doctor.py` |
| `contacts.json` | Contacts + phone numbers (fast wa.me path) + misheard aliases |
| `tts.py` | edge-tts + playback (miniaudio decode + sounddevice) |
| `config.py` | Models, voices, thresholds |

## Notes / Hacks jo demo mein kaam aaye

- Whisper auto-detect Urdu ko Hindi aur Pashto ko Arabic samajhta hai — `stt.py` mein
  forced-language retry (`hi→ur`, `ar→ps`) isko fix karta hai.
- Pashto ke liye Edge-TTS ke native voices (`ps-AF-GulNawazNeural`) use hue —
  text-fallback ki zaroorat nahi padi.
- GPT-OSS-20B (Groq free tier) primary hai — tool-JSON parsing mein sab se reliable
  aur fastest. 120b fallback hai. Pashto input kabhi kabhi JSON parse-fail deta hai —
  brain.py mein alternate-model retry loop isko handle karta hai.
- Screen recording 15 fps tick-based pacing use karti hai — grab slow ho to bhi
  playback duration real time ke barabar rehta hai. 5-minute safety cap hai.

## Known Limitations

- **Server.py runs on 0.0.0.0 without authentication.** Any device on the same
  WiFi network can access it and trigger voice commands, WhatsApp messages,
  or emails. This is an intentional trade-off for a local-network hackathon
  demo, not an oversight — production use would need auth.