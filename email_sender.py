"""Email sending via Gmail SMTP (free, no paid API).

ONE-TIME SETUP REQUIRED:
1. Use a Gmail account (or any SMTP provider — adjust SMTP_HOST/PORT below).
2. Turn on 2-Step Verification on that Google account.
3. Create an "App Password": Google Account -> Security -> 2-Step
   Verification -> App passwords -> generate one for "Mail".
   (Your normal Gmail password will NOT work here — Google blocks it.)
4. Add to your .env file:
       EMAIL_ADDRESS=youraccount@gmail.com
       EMAIL_APP_PASSWORD=the16charapppassword

LIMITATION: like WhatsApp, this needs a real email ADDRESS, not just a
name. Add contacts to EMAIL_CONTACTS below (name -> email address) so the
assistant can resolve "email Asif" to an actual inbox.
"""
import json
import os
import smtplib
import difflib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

# name (as you'll say it out loud) -> real email address.
# Loaded from email_contacts.json (gitignored — keeps personal addresses out
# of the repo). Falls back to a demo example if the file doesn't exist yet.
_CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "email_contacts.json")


def _load_email_contacts() -> dict:
    try:
        with open(_CONTACTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, str) and "@" in v} if isinstance(data, dict) else {}
    except Exception:
        return {"friend": "friend@example.com"}


EMAIL_CONTACTS = _load_email_contacts()

_email_contacts_lock = threading.Lock()


def save_email_contact(name: str, address: str) -> str:
    """Save/update an email contact by voice: write-through to the gitignored
    email_contacts.json and refresh the in-memory snapshot used for
    resolution. Address must contain '@' and a dot in the domain."""
    name = (name or "").strip().lower()
    address = (address or "").strip()
    if not name:
        return "Error: contact ka naam nahi mila."
    if "@" not in address or "." not in address.split("@")[-1]:
        return "Error: email address poori nahi lagi — dobara bolein."
    raw = {}
    if os.path.exists(_CONTACTS_FILE):
        try:
            with open(_CONTACTS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
        except Exception as e:
            print(f"⚠  email_contacts.json unreadable ({e}) — starting a fresh one")
            raw = {}
    raw[name] = address
    with _email_contacts_lock:
        tmp = _CONTACTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CONTACTS_FILE)  # atomic
    global EMAIL_CONTACTS
    EMAIL_CONTACTS = _load_email_contacts()  # refresh resolution snapshot
    print(f"💾 Email contact saved: {name} -> {address}")
    return f"Email contact saved: {name}"


class EmailError(Exception):
    """Clear, speakable error — the assistant reads this aloud on failure."""


def _resolve_email(heard_name: str):
    h = heard_name.strip().lower()
    for name, addr in EMAIL_CONTACTS.items():
        if h == name.lower():
            return addr
    match = difflib.get_close_matches(heard_name, list(EMAIL_CONTACTS.keys()), n=1, cutoff=0.5)
    if match:
        return EMAIL_CONTACTS[match[0]]
    # Maybe the user just spoke the address itself (rare, but possible)
    if "@" in heard_name:
        return heard_name.strip()
    return None


def send_email(to: str, subject: str, body: str) -> str:
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise EmailError(
            "Email set up nahi hai. .env file mein EMAIL_ADDRESS aur "
            "EMAIL_APP_PASSWORD add karen (dekhen email_sender.py ke top comments)."
        )

    address = _resolve_email(to)
    if not address:
        raise EmailError(
            f"'{to}' ka email address nahi mila. email_sender.py mein "
            f"EMAIL_CONTACTS list mein add karen."
        )

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = address
    msg["Subject"] = subject or "(no subject)"
    # Missing Date/Message-ID headers are a classic spam-filter trigger for
    # script-sent mail — Gmail's own web UI adds these automatically, but
    # smtplib does not, so we set them explicitly.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, address, msg.as_string())
        return f"Email sent to {to} ({address})"
    except smtplib.SMTPAuthenticationError:
        raise EmailError(
            "Gmail login fail hua — App Password sahi nahi hai ya 2-Step "
            "Verification on nahi hai. Setup instructions dekhen email_sender.py mein."
        )
    except Exception as e:
        raise EmailError(f"{type(e).__name__}: {str(e)[:150]}")