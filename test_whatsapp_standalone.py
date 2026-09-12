r"""
test_whatsapp_standalone.py — quick diagnostic: does the persistent Edge
driver launch at all? (Run directly:  venv\Scripts\python test_whatsapp_standalone.py)
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("Step 1: importing whatsapp_bot...")
import whatsapp_bot

print(f"Step 2: profile folder -> {whatsapp_bot.EDGE_PROFILE}")

print("Step 3: launching Edge with the persistent profile...")
try:
    driver = whatsapp_bot.get_or_start_driver()
    print("SUCCESS: Edge launched fine!")
    print("Title of blank page:", driver.title)
    whatsapp_bot.shutdown()
except whatsapp_bot.WaError as e:
    print(f"FAILED (WaError): {e}")
except Exception as e:
    print(f"FAILED at driver launch: {type(e).__name__}: {e}")
