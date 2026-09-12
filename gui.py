"""
gui.py — SAATHI desktop window (replaces the plain command-prompt loop).

Run this instead of `python main.py`:
    venv\\Scripts\\python gui.py

Everything (STT, brain, executor, TTS) runs on a background thread so the
window never freezes while listening / thinking / speaking.
"""
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import executor  # noqa: F401  (registers tools with brain — must import before brain.think)
import audio_io
import stt
from brain import think
import tts
from main import detect_script, FALLBACKS

BG = "#0f1115"
PANEL = "#1a1d24"
ACCENT = "#5b8cff"
TEXT = "#e8e8ea"
SUBTLE = "#8a8f98"
USER_BUBBLE = "#2a2f3a"
BOT_BUBBLE = "#22314f"


class SaathiGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SAATHI")
        self.root.geometry("480x680")
        self.root.configure(bg=BG)
        self.history = []
        self.listening_thread = None
        self.is_busy = False

        self._build_ui()

    # ---------------- UI layout ----------------
    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG, pady=16)
        header.pack(fill="x")
        tk.Label(header, text="SAATHI", font=("Segoe UI", 20, "bold"),
                 fg=TEXT, bg=BG).pack()
        tk.Label(header, text="اردو (پاکستانی)  •  English",
                 font=("Segoe UI", 10), fg=SUBTLE, bg=BG).pack(pady=(2, 0))

        # Chat area
        chat_frame = tk.Frame(self.root, bg=BG)
        chat_frame.pack(fill="both", expand=True, padx=14, pady=(4, 8))

        self.chat = scrolledtext.ScrolledText(
            chat_frame, wrap="word", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 11), relief="flat", padx=12, pady=12,
            state="disabled", borderwidth=0,
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("user", foreground="#9db4ff", spacing3=10,
                                 font=("Segoe UI", 11, "bold"))
        self.chat.tag_configure("bot", foreground=TEXT, spacing3=14,
                                 font=("Segoe UI", 11))
        self.chat.tag_configure("sys", foreground=SUBTLE, spacing3=8,
                                 font=("Segoe UI", 9, "italic"))

        # Status row
        self.status_var = tk.StringVar(value="Tap the mic to speak")
        tk.Label(self.root, textvariable=self.status_var, font=("Segoe UI", 10),
                 fg=SUBTLE, bg=BG).pack(pady=(0, 6))

        # Mic button
        btn_frame = tk.Frame(self.root, bg=BG, pady=10)
        btn_frame.pack()
        self.mic_btn = tk.Canvas(btn_frame, width=76, height=76, bg=BG,
                                  highlightthickness=0, cursor="hand2")
        self.mic_circle = self.mic_btn.create_oval(4, 4, 72, 72, fill=ACCENT, outline="")
        self.mic_btn.create_text(38, 38, text="🎤", font=("Segoe UI", 24))
        self.mic_btn.pack()
        self.mic_btn.bind("<Button-1>", lambda e: self.on_mic_click())

        # Text fallback entry (typed input — handy for quick demo/testing)
        entry_frame = tk.Frame(self.root, bg=BG, pady=8)
        entry_frame.pack(fill="x", padx=14)
        self.entry = tk.Entry(entry_frame, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                               font=("Segoe UI", 11), relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.on_text_submit())
        send_btn = tk.Button(entry_frame, text="➤", command=self.on_text_submit,
                              bg=ACCENT, fg="white", relief="flat",
                              font=("Segoe UI", 11, "bold"), width=3)
        send_btn.pack(side="right")

        self._append_system("SAATHI ready. Mic dabayen ya type karen.")

    # ---------------- Chat helpers ----------------
    def _append_system(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{text}\n", "sys")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _append_user(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"You\n", "user")
        self.chat.insert("end", f"{text}\n\n", "bot")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _append_bot(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"SAATHI\n", "user")
        self.chat.insert("end", f"{text}\n\n", "bot")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def _set_mic_color(self, color):
        self.mic_btn.itemconfig(self.mic_circle, fill=color)

    # ---------------- Actions ----------------
    def on_mic_click(self):
        if self.is_busy:
            return
        self.is_busy = True
        self._set_mic_color("#ff5b5b")  # red while active
        threading.Thread(target=self._voice_turn, daemon=True).start()

    def on_text_submit(self):
        text = self.entry.get().strip()
        if not text or self.is_busy:
            return
        self.entry.delete(0, "end")
        self.is_busy = True
        threading.Thread(target=self._text_turn, args=(text,), daemon=True).start()

    # ---------------- Background workers ----------------
    def _voice_turn(self):
        try:
            self._set_status("Sun raha hoon...")
            audio = audio_io.record_until_silence()
            if audio is None:
                self._set_status("Kuch sunai nahi diya. Dobara try karen.")
                return

            self._set_status("Samajh raha hoon...")
            text, lang = stt.transcribe(audio)
            if not text:
                self._set_status("Samajh nahi aaya. Dobara bolein.")
                return

            self.root.after(0, self._append_user, text)
            self._process(text)
        except Exception as e:
            self._set_status(f"Error: {str(e)[:60]}")
        finally:
            self.is_busy = False
            self.root.after(0, lambda: self._set_mic_color(ACCENT))
            self._set_status("Tap the mic to speak")

    def _text_turn(self, text):
        try:
            self.root.after(0, self._append_user, text)
            self._process(text)
        finally:
            self.is_busy = False
            self._set_status("Tap the mic to speak")

    def _process(self, text):
        self._set_status("Soch raha hoon...")
        try:
            reply = think(text, self.history)
        except Exception as e:
            print(f"Error: {str(e)[:80]}")
            reply = FALLBACKS[len(self.history) % len(FALLBACKS)]

        self.root.after(0, self._append_bot, reply)

        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": reply})
        del self.history[:-10]

        self._set_status("Bol raha hoon...")
        try:
            tts.speak(reply, detect_script(reply))
        except Exception as e:
            print(f"TTS failed: {str(e)[:60]}")


def main():
    root = tk.Tk()
    SaathiGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()