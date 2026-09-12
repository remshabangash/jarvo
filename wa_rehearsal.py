r"""wa_rehearsal.py — DRY-RUN the full WhatsApp send flow WITHOUT sending.

Runs every step the real send does — persistent browser, WhatsApp Web load,
login check, contact resolution, deep-link composer — and stops right before
pressing Enter. Optionally sends a real test message if you confirm.

Run:
    venv\Scripts\python wa_rehearsal.py "Asif"
"""
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from selenium.webdriver.common.by import By

import whatsapp_bot


def _deep_link_rehearsal(d, phone: str) -> int:
    digits = whatsapp_bot.digits_fmt(phone)
    test_text = "SAATHI rehearsal - ye message SEND NAHI hoga"
    print(f"      wa.me deep link: ...send?phone={digits}&text=...")
    d.get(f"https://web.whatsapp.com/send?phone={digits}&text={test_text}")
    box = None
    end = time.time() + 30
    while time.time() < end:
        box = whatsapp_bot._find_now(d, whatsapp_bot.COMPOSER_XPATHS)
        if box:
            break
        if whatsapp_bot._find_now(d, whatsapp_bot.INVALID_NUMBER_XPATHS):
            print(f"      FAIL: number {digits} WhatsApp par nahi mila.")
            return 1
        if whatsapp_bot._qr_visible(d):
            print("      FAIL: QR nazar aa gaya — session expire.")
            return 1
        time.sleep(0.5)
    if box is None:
        print("      FAIL: composer nahi mila (timeout).")
        whatsapp_bot._shot(d)
        return 1
    print("      OK — composer mil gaya, message pre-filled.")
    print("      STOP — Enter press nahi kiya, kuch send nahi hua.")
    d.back()
    time.sleep(1)
    return 0


def rehearsal(contact: str) -> int:
    print("=" * 56)
    print(f"  SAATHI WhatsApp REHEARSAL (send ke baghair) — '{contact}'")
    print("=" * 56)

    print("\n[1/4] Contact resolution...")
    name, phone = whatsapp_bot.resolve_contact(contact)
    where = f"(phone: {phone})" if phone else "(search flow — phone nahi likha)"
    print(f"      Heard '{contact}' -> resolved: '{name}' {where}")

    print("\n[2/4] Persistent Edge launch...")
    try:
        d = whatsapp_bot.get_or_start_driver()
        print("      OK — Edge chal gaya (persistent profile).")
    except Exception as e:
        print(f"      FAIL: {e}")
        print("      -> Purani Edge/WhatsApp window band karein, dobara chalayein.")
        return 1

    print("\n[3/4] WhatsApp Web load + login check...")
    try:
        d = whatsapp_bot.ensure_whatsapp_loaded(timeout=60)
        print("      OK — logged in, chat list loaded.")
    except Exception as e:
        print(f"      FAIL: {e}")
        if "login" in str(e).lower():
            print("      -> Fix: venv\\Scripts\\python whatsapp_login.py  (QR scan)")
        return 1

    rc = 0
    if phone:
        print("\n[4/4] Deep-link composer (bina Enter)...")
        try:
            rc = _deep_link_rehearsal(d, phone)
        except Exception as e:
            print(f"      FAIL: {type(e).__name__}: {e}")
            whatsapp_bot._shot(d)
            rc = 1
    else:
        print("\n[4/4] SKIPPED (contacts.json mein phone number nahi).")
        print("      Number add karein to asli sends 100% reliable ho jayenge.")

    if rc == 0:
        print("\n✅ Rehearsal complete — flow ready hai.")
        try:
            go_ahead = input("Ab ASLI test message bhejun? (haan/nahi): ").strip().lower()
        except EOFError:
            go_ahead = "nahi"  # non-interactive run
        if go_ahead in ("haan", "han", "yes", "y"):
            try:
                result = whatsapp_bot.send_message(
                    contact, "SAATHI test - WhatsApp link verified")
                print(f"📤 SUCCESS: {result}")
            except whatsapp_bot.WaError as e:
                print(f"❌ FAIL: {e}")
                print(f"   📸 Screenshot: {whatsapp_bot.ERROR_SHOT}")
                rc = 1
    else:
        print("\n⚠  Rehearsal mein masla tha — upar dekhein. Screenshot:", whatsapp_bot.ERROR_SHOT)
    return rc


if __name__ == "__main__":
    contact = sys.argv[1] if len(sys.argv) > 1 else "Asif"
    sys.exit(rehearsal(contact))
