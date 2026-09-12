"""Microphone capture with ambient-noise calibration and speech padding.

Records until the user stops speaking. Returns (np.int16 array, sample_rate).
Threshold is calibrated live from ambient noise — no hardcoding per mic.
"""
import numpy as np
import sounddevice as sd

import config

_cached_threshold = None  # measured once, reused every turn (was re-measuring every call)


def calibrate_ambient(duration: float = None, force: bool = False) -> float:
    """Measure ambient noise floor for a moment; returns calibrated RMS.

    Cached after the first call so we don't burn ~0.7s of silence at the
    start of every single turn — this was a big chunk of the "slow response"
    feeling. Pass force=True to re-measure (e.g. if the room gets noisier).
    """
    global _cached_threshold
    if _cached_threshold is not None and not force:
        return _cached_threshold

    duration = duration or config.AMBIENT_CALIB_SECONDS
    chunk = int(config.SAMPLE_RATE * 0.1)
    frames = []

    def cb(indata, n, t, s):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=chunk, callback=cb):
        sd.sleep(int(duration * 1000))

    if not frames:
        return config.THRESHOLD_FLOOR
    audio = np.concatenate(frames).astype(np.float32)
    rms = float(np.sqrt(np.mean(np.square(audio))))
    # threshold = ambient * 1.8, with a floor so dead mics still work.
    # (was *2.2 — too strict for a soft/normal speaking voice, causing
    # "mic doesn't hear me" on quieter mics/voices)
    _cached_threshold = max(config.THRESHOLD_FLOOR, rms * 1.8)
    return _cached_threshold


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame.astype(np.float32)))))


def _normalize_loudness(audio: np.ndarray, target_peak: float = 0.85) -> np.ndarray:
    """Boost quiet recordings up to a healthy peak level before sending to
    Whisper. A quiet/far mic is one of the biggest causes of misheard or
    partially-heard speech. Loud recordings are left untouched."""
    peak = np.abs(audio.astype(np.float32)).max()
    if peak < 1:
        return audio
    target = target_peak * 32767
    if peak >= target:
        return audio
    gain = target / peak
    boosted = np.clip(audio.astype(np.float32) * gain, -32768, 32767)
    return boosted.astype(np.int16)


def record_until_silence(max_wait_for_speech: float = 6.0):
    """Block until a full utterance is captured. Returns np.int16 array or None."""
    chunk = int(config.SAMPLE_RATE * 0.1)  # 100 ms chunks
    # Recalibrate every turn (not just once at startup). A hackathon room's
    # noise floor changes constantly (crowd, other demos, mic distance) —
    # a stale cached threshold was the main reason the mic randomly stopped
    # picking up speech or cut it off mid-word.
    threshold = calibrate_ambient(force=True)

    frames = []
    max_frames = int(config.MAX_RECORD_SECONDS * config.SAMPLE_RATE / chunk)

    got_speech = False
    silence_after_speech = 0.0
    speech_frames = 0
    peak_level = 0.0  # loudest frame while speaking (for end-of-turn threshold)
    speech_start_frame = 0  # where speech began (for leading-silence trim)
    onset_streak = 0  # consecutive frames above threshold, before we commit to "speech started"
    ONSET_FRAMES_NEEDED = 2  # ~0.2s sustained — filters clicks/coughs/mic-tap noise

    print("🎤 Listening...")

    def callback(indata, frames_count, time_info, status):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=chunk, callback=callback):
        processed = 0
        while processed < max_frames:
            if processed >= len(frames):
                sd.sleep(10)  # wait for next 100ms frame
                continue
            frame = frames[processed]
            processed += 1
            level = _rms(frame)

            if not got_speech:
                if level > threshold:
                    onset_streak += 1
                    if onset_streak >= ONSET_FRAMES_NEEDED:
                        got_speech = True
                        speech_frames = onset_streak
                        peak_level = level
                        # keep a lead-in before the first spoken frame (covers
                        # the onset streak itself + a little extra)
                        speech_start_frame = max(0, processed - onset_streak - 1)
                        print("🗣  Speech detected...")
                elif (processed * 0.1) > max_wait_for_speech:
                    print("⏱  No speech detected.")
                    return None
                else:
                    onset_streak = 0
            else:
                if level > peak_level:
                    peak_level = level
                # End-of-turn: silence must be quiet RELATIVE to how loudly the
                # user speaks. A fixed threshold cut phrases short whenever
                # the mic gain was low; 55% of the user's own peak level does
                # not (peaks are ~2-6x the mean speaking level).
                silence_cut = max(threshold, peak_level * 0.4)
                if level < silence_cut:
                    silence_after_speech += 0.1
                    if silence_after_speech >= config.SILENCE_SECONDS:
                        break
                else:
                    silence_after_speech = 0.0
                    speech_frames += 1

    if not got_speech or not frames:
        return None

    duration_s = speech_frames * 0.1
    if duration_s < config.MIN_SPEECH_SECONDS:
        print("🔇 Too short / noise — ignored.")
        return None

    audio = np.concatenate(frames, axis=0)
    # Trim LEADING silence: everything before the user actually started
    # speaking (plus the 0.2s lead-in) never reaches Whisper — shorter
    # uploads, faster transcription, and no risk of the model reacting to
    # room noise instead of the first word.
    lead_trim = speech_start_frame * chunk
    if lead_trim and lead_trim < audio.shape[0]:
        audio = audio[lead_trim:, :]
    # Trim trailing silence (measured after the last spoken frame)
    if silence_after_speech > 0:
        trim = int(silence_after_speech * config.SAMPLE_RATE)
        if trim < audio.shape[0]:
            audio = audio[:-trim, :]
    print(f"✅ Captured {audio.shape[0] / config.SAMPLE_RATE:.1f}s")
    return _normalize_loudness(audio)