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
import os
import smtplib
import difflib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

# name (as you'll say it out loud) -> real email address
EMAIL_CONTACTS = {
    "remsha": "bangashremsha0@gmail.com",
    "remsha0": "bangashremsha0@gmail.com",
    "bangashremsha0": "bangashremsha0@gmail.com",
}


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