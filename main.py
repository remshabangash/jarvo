"""JARVO — multilingual voice assistant main loop.

Pipeline: Mic → Whisper STT → LLM brain (tools) → Executor → TTS
Run:  venv\\Scripts\\python main.py            (voice mode)
      venv\\Scripts\\python main.py --text     (text-mode backup)
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import executor  # registers tools with brain (must be imported before brain.think)
from brain import think, set_pre_speech
import tts
import whatsapp_bot


def detect_script(s: str) -> str:
    """Pick TTS voice from the reply text's script: Pashto → Urdu → English.

    Script presence beats position: an Urdu/Arabic-script char ANYWHERE in the
    reply selects the Urdu voice (an English word at the start like "Ok," or
    "WhatsApp" must not make the whole Urdu sentence be read in English).
    """
    # Pashto-only letters (not used in Urdu) get the Pashto voice
    if any(c in "ږړښڼڅژډټ" for c in s):
        return "ps"
    has_urdu = False
    for ch in s:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            has_urdu = True
            break
    return "ur" if has_urdu else "en"


FALLBACKS = [
    "Maaf kijiye, thori mushkil ho rahi hai. Dobara bolein.",
    "Sorry, thora masla aa gaya. Dobara koshish karein.",
]


def _warmup():
    """Silent startup warm-up: TTS synth (no play) + ambient calibration.

    First real command then skips ~2-4s of one-time initialization cost.
    """
    try:
        tts.prepare("JARVO ready.", "en")
    except Exception:
        pass
    try:
        import audio_io
        audio_io.calibrate_ambient()
    except Exception:
        pass
    # Pre-load WhatsApp in the BACKGROUND so a voice command like
    # "Asif ko hello bhejo" doesn't pay the 15-40s web-app load itself.
    try:
        whatsapp_bot.warm_up(background=True)
    except Exception:
        pass


def handle_input(text: str, history: list) -> bool:
    """Process one user input. Returns False to exit. Never raises."""
    text = text.strip()
    if not text:
        return True
    print(f"👤 You: {text}")

    if text.lower().strip(" .!") in ("quit", "exit", "band karo", "خداحافظ", "بس"):
        print("👋 Allah Hafiz!")
        try:
            tts.speak("Allah Hafiz!", "ur")
        except Exception:
            pass
        whatsapp_bot.shutdown()
        return False

    try:
        reply = think(text, history)
    except Exception as e:
        # Rate limit exhausted, network down, etc. — demo must go on.
        print(f"⚠  Error: {str(e)[:80]}")
        reply = FALLBACKS[len(history) % len(FALLBACKS)]

    print(f"🤖 JARVO: {reply}")

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    del history[:-10]  # keep last 5 exchanges (in-place trim)

    try:
        tts.speak(reply, detect_script(reply))
    except Exception as e:
        print(f"⚠  TTS failed: {str(e)[:60]} — reply text par available hai.")
    return True


def voice_loop():
    import audio_io
    import stt

    history = []
    while True:
        try:
            audio = audio_io.record_until_silence()
            if audio is None:
                continue

            text, lang = stt.transcribe(audio)
            if not text:
                print("⚠  Samajh nahi aaya — dobara bolein.")
                try:
                    tts.speak("Maaf kijiye, samajh nahi aaya. Dobara bolein.", "ur")
                except Exception:
                    pass
                continue

            if not handle_input(text, history):
                break
        except KeyboardInterrupt:
            print("\n👋 Allah Hafiz!")
            break
        except Exception as e:
            # Never let one bad cycle kill the loop (mic glitch, API hiccup…)
            print(f"⚠  Cycle error: {str(e)[:80]} — dobara koshish...")
            continue


def text_loop():
    print("⌨️  Text mode — likh kar test karein (quit = exit).\n")
    history = []
    while True:
        try:
            text = input("👤 > ")
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Allah Hafiz!")
            break
        try:
            if not handle_input(text, history):
                break
        except Exception as e:
            print(f"⚠  Cycle error: {str(e)[:80]} — dobara koshish...")


def main():
    print("=" * 52)
    print("  JARVO — Voice Assistant (Urdu / English / Pashto)")
    print("=" * 52)

    set_pre_speech(lambda text: tts.speak(text, "ur"))

    if "--text" not in sys.argv:
        print("⚡ Warming up (TTS + mic calibration)...")
        _warmup()
        print("✅ Ready — bolein!\n")

    if "--text" in sys.argv:
        text_loop()
    else:
        voice_loop()


if __name__ == "__main__":
    main()