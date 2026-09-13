"""mic_test.py — JARVO mic diagnostic tool.

Kya check karta hai:
  1. Kaunse mic devices available hain (aur default kaunsa hai)
  2. Har mic se 4 second ki test recording ka LEVEL (peak/RMS)
  3. Verdict: mic sahi chal raha hai, quiet hai, ya almost band hai

Run:
    venv\\Scripts\\python mic_test.py             # full check + compare
    venv\\Scripts\\python mic_test.py --loop      # live level meter
    venv\\Scripts\\python mic_test.py --device 2  # khaas device test karo
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import queue
import time

import numpy as np
import sounddevice as sd


def list_input_devices():
    print("=== INPUT DEVICES ===")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            marker = "  <== DEFAULT" if i == sd.default.device[0] else ""
            print(f'[{i:>2}] {d["name"][:58]:<58}{marker}')
    print()


def _record_level(device, seconds=4.0, samplerate=16000):
    """Record `seconds` from `device`, return (peak, rms, clipped_frac)."""
    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata.copy())

    with sd.InputStream(device=device, samplerate=samplerate, channels=1,
                        dtype="int16", blocksize=int(samplerate * 0.1), callback=cb):
        frames = []
        end = time.time() + seconds
        while time.time() < end:
            try:
                frames.append(q.get(timeout=0.5))
            except queue.Empty:
                pass
    if not frames:
        return 0.0, 0.0, 0.0
    audio = np.concatenate(frames).astype(np.float32)
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(np.square(audio))))
    clipped = float((np.abs(audio) > 32000).mean())
    return peak, rms, clipped


def verdict(peak, rms, clipped=0.0):
    if peak < 100:
        return "❌ BAND/MUTE lag raha hai (koi awaz nahi aa rahi)"
    if peak < 1000:
        return "⚠  BAHUT QUIET — mic door hai ya gain kam hai"
    if peak > 32000 or clipped > 0.01:
        return "⚠  CLIPPING — bahut loud, gain kam karo"
    return "✅ THEEK — awaz sahi level par aa rahi hai"


def test_device(idx, seconds=4.0):
    name = sd.query_devices(idx)["name"]
    print(f"\n🎤 [{idx}] {name[:58]}")
    print("   ... 4 second BOLO ya awaz karo ...")
    peak, rms, clipped = _record_level(idx, seconds)
    print(f"   Peak: {peak:>8.0f} | RMS: {rms:>8.0f} | Clipped: {clipped*100:.1f}%")
    print(f"   {verdict(peak, rms, clipped)}")
    return peak


def live_meter(device=None, seconds=15):
    """Real-time level meter — bol kar dekho kitni lines bharti hain."""
    dev = device if device is not None else sd.default.device[0]
    print(f"🔴 LIVE METER ({sd.query_devices(dev)['name'][:50]}) — {seconds}s tak bolo!\n")
    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata.copy())

    with sd.InputStream(device=dev, samplerate=16000, channels=1,
                        dtype="int16", blocksize=1600, callback=cb):
        end = time.time() + seconds
        while time.time() < end:
            try:
                frame = q.get(timeout=0.5)
            except queue.Empty:
                continue
            rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float32)))))
            bars = int(min(60, rms / 150))
            print(f"   {'█' * bars:<60} {rms:6.0f}")


def main():
    args = sys.argv[1:]
    list_input_devices()

    if "--loop" in args:
        dev = None
        if "--device" in args:
            dev = int(args[args.index("--device") + 1])
        live_meter(dev)
        return

    devices = []
    if "--device" in args:
        devices = [int(args[args.index("--device") + 1])]
    else:
        # Compare candidates: default + internal/external mics
        seen_names = set()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] <= 0:
                continue
            n = d["name"].lower()
            if any(k in n for k in ("microphone", "mic")) and n not in seen_names:
                seen_names.add(n)
                devices.append(i)

    results = {}
    for idx in devices:
        try:
            results[idx] = test_device(idx)
        except Exception as e:
            print(f"   ⚠  [{idx}] test fail: {type(e).__name__}: {str(e)[:60]}")

    print("\n" + "=" * 62)
    if results:
        best = max(results, key=results.get)
        print(f"🏆 BEST DEVICE: [{best}] {sd.query_devices(best)['name'][:50]}")
        print(f"   Use karo:  set JARVO_MIC_DEVICE={best}")
        print("   (ya config.py mein JARVO_MIC_DEVICE = " + str(best) + " set karo)")
    print("=" * 62)


if __name__ == "__main__":
    main()
