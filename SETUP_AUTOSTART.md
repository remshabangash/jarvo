# Make SAATHI auto-open when you say "Hi SAATHI"

This makes a small background listener start automatically every time you
turn on your laptop. It does NOT run the full SAATHI server all the time —
it just listens for the wake word, and only then starts the server and
opens the browser for you.

## One-time setup (2 minutes)

1. **Test it manually first.** Double-click `run_wake_listener_silent.vbs`
   in the project folder. Nothing visible will happen (that's expected —
   it's silent). Wait ~5 seconds, then say **"Hi SAATHI"** clearly. The
   SAATHI server should start and your browser should open automatically.

   To stop it while testing, open Task Manager (Ctrl+Shift+Esc), find
   `pythonw.exe`, and click "End Task".

2. **Add it to Windows Startup:**
   - Press `Win + R`, type `shell:startup`, press Enter. A folder opens.
   - Right-click inside that folder → **New → Shortcut**.
   - Browse to and select `run_wake_listener_silent.vbs` in your project
     folder (e.g. `C:\Users\Aamir\OneDrive\Desktop\saathi_assistant\`).
   - Finish creating the shortcut.

3. **Restart your laptop** to confirm it works from a real cold boot. After
   logging in, wait ~10 seconds, then say "Hi SAATHI" — it should open on
   its own.

## Notes

- This uses your existing Groq API key and only sends audio to Groq when
  the microphone actually picks up speech — it is silent (no network
  calls, no cost) the rest of the time.
- If it ever mishears background noise as "SAATHI" and opens by mistake,
  just close the tab — the listener keeps running quietly for next time.
- To remove autostart later: go back to `shell:startup` and delete the
  shortcut.