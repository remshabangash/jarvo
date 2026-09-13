"""JARVO WhatsApp doctor — one command, tells you EXACTLY what is broken.

Run:
    venv\\Scripts\\python wa_doctor.py

Checks, in order:
  1. Edge browser can launch with the persistent profile
  2. WhatsApp Web loads
  3. You are logged in (no QR screen)
  4. Your contacts.json has at least one phone-number contact
  5. (optional) sends a test message to a contact: python wa_doctor.py "Naam"
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import whatsapp_bot


def main():
    print("=" * 56)
    print("  JARVO — WhatsApp Doctor")
    print("=" * 56)

    print("\n[1/4] Edge browser launch (persistent profile)...")
    try:
        d = whatsapp_bot.get_or_start_driver()
        print("      OK — Edge chal gaya.")
    except Exception as e:
        print(f"      FAIL: {e}")
        print("      -> Agar 'already in use' aaye: purani Edge window band karein.")
        return 1

    print("\n[2/4] WhatsApp Web load (slow net par 1-2 minute lag sakta hai)...")
    try:
        d = whatsapp_bot.ensure_whatsapp_loaded(timeout=150)
        print("      OK — WhatsApp Web loaded.")
    except Exception as e:
        print(f"      FAIL: {e}")
        if "login" in str(e).lower():
            print("      -> Fix: venv\\Scripts\\python whatsapp_login.py  (QR scan)")
        return 1

    print("\n[3/4] Login status...")
    s = whatsapp_bot.status()
    print(f"      {s}")
    if "NOT LOGGED" in s:
        print("      -> Fix: venv\\Scripts\\python whatsapp_login.py  (QR scan)")
        return 1

    print("\n[4/4] contacts.json...")
    contacts = whatsapp_bot._load_contacts()
    with_phone = {n: v for n, v in contacts.items() if v["phone"]}
    print(f"      Total contacts: {len(contacts)}, with phone: {len(with_phone)}")
    for n in list(with_phone)[:5]:
        print(f"        - {n} ({with_phone[n]['phone']})")
    if not with_phone:
        print("      ⚠  Kisi contact ka phone number nahi likha — messages search")
        print("         flow se jayenge (slow/unreliable). contacts.json kholein.")

    # Optional live test send
    if len(sys.argv) > 1:
        name = sys.argv[1]
        print(f"\n[TEST SEND] '{name}' ko test message bhej raha hoon...")
        try:
            result = whatsapp_bot.send_message(name, "JARVO test — WhatsApp link verified ✅")
            print(f"      SUCCESS: {result}")
        except Exception as e:
            print(f"      FAIL: {e}")
            print(f"      📸 Screenshot dekhein: {whatsapp_bot.ERROR_SHOT}")
            return 1

    print("\n✅ Doctor finished — WhatsApp link ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
