# SAATHI local agent

SAATHI can be used with a separately hosted web page while actions still run on each user's own computer.

## How it works

1. The user starts this Python app locally.
2. The user opens the hosted SAATHI page.
3. The page automatically calls `http://127.0.0.1:5000` as the local agent.
4. WhatsApp, browser automation, screenshots, microphone capture, TTS, and app launching happen on that user's computer.

The hosted page can also select an explicit agent URL with:

```text
https://your-demo-site.example/?agent=http://127.0.0.1:5000
```

## Local setup

Python 3.10 or newer is recommended.

### One-click Windows setup

Download the project, unzip it, and double-click `install_windows.bat`. The
script creates the virtual environment, installs dependencies, asks for the
Groq key, starts the local agent, and opens the local SAATHI page. It does not
open WhatsApp automatically.

After setup, users can double-click `install_windows.bat` again to start the
agent. They only need to run `whatsapp_login.py` if they want WhatsApp
automation.

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
venv\Scripts\python whatsapp_login.py
venv\Scripts\python Server.py
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 Server.py
```

The included `start_saathi.sh` performs the final configuration prompt and
starts the local server after the dependencies have been installed.

Create `.env` with at least:

```env
GROQ_API_KEY=gsk_your_key
```

The agent listens on `127.0.0.1:5000` by default. Verify it is ready:

```bash
curl http://127.0.0.1:5000/api/health
```

Expected response:

```json
{ "agent": "saathi", "ok": true, "service": "local" }
```

## Hosted frontend

Upload `static/index.html` to Vercel, GitHub Pages, or another static host.
Publish `install_windows.bat` as the download users run once. When a visitor
opens the hosted page, it automatically checks their local port `5000`.

They must run the local agent first. The hosted page cannot control their machine until the agent is running.

## Demo notes

- Each user needs their own Groq configuration unless the cloud backend is later added.
- Each WhatsApp user must complete their own WhatsApp Web QR login.
- The local agent intentionally has broad desktop permissions because it can open apps and capture the screen.
- The current CORS behavior is intended for a hackathon demo and should be restricted before production use.
- The agent uses in-memory conversation history and is designed for one local user per process.
