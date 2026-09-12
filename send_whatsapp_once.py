"""
send_whatsapp_once.py — sends ONE WhatsApp message and exits.

Kept for CLI/debug use (executor now sends in-process via the persistent
browser). Prints exactly one line: the result or the error.

Usage:
    python send_whatsapp_once.py "<contact>" "<message>"
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if __name__ == "__main__":
    import traceback

    if len(sys.argv) < 3:
        print("WhatsApp error: missing contact/message arguments")
        sys.stdout.flush()
        sys.exit(1)

    contact = sys.argv[1]
    message = sys.argv[2]

    try:
        import whatsapp_bot
        result = whatsapp_bot.send_message(contact, message)
        print(result)
    except whatsapp_bot.WaError as e:
        print(f"WhatsApp error: {e}")
    except Exception:
        print("WhatsApp error: subprocess crashed:")
        print(traceback.format_exc())
    finally:
        whatsapp_bot.shutdown()
        sys.stdout.flush()
