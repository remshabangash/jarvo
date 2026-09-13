# JARVO WhatsApp one-time login: saves session so voice commands never need QR again
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import whatsapp_bot

print("Edge khul raha hai — WhatsApp Web ka QR scan karein (sirf pehli baar).")
print("Chat list load hone tak intezaar karein, phir yahan Enter dabaein.")

driver = whatsapp_bot.get_or_start_driver()
try:
    whatsapp_bot.ensure_whatsapp_loaded(timeout=120)
    print("✅ Login detect ho gaya — session saved!")
except Exception as e:
    print(f"⚠  {e}")
    print("   (Agar QR scan nahi hua to dobara chalayein.)")
finally:
    input("Enter dabaein browser band karne ke liye...")
    whatsapp_bot.shutdown()
    print("Done. Ab voice se message bhej sakte hain — ya check karein: venv\\Scripts\\python wa_doctor.py")
