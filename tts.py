"""Text-to-Speech via edge-tts (free) with playback."""
import asyncio
import os
import tempfile
import threading
import uuid

import edge_tts

import config

# Serialize actual speech: two overlapping voices would be unintelligible
# anyway, and sharing one file between concurrent speak() calls caused
# corrupt-playback crashes (miniaudio.DecodeError). A unique temp file per
# call + this lock eliminates both problems.
_speak_lock = threading.Lock()


async def _synthesize(text: str, lang: str, path: str) -> None:
    voice = config.TTS_VOICES.get(lang, config.TTS_VOICES["en"])
    tts = edge_tts.Communicate(text, voice)
    await tts.save(path)


def _run_async(coro) -> None:
    try:
        asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()


def _play(path: str) -> None:
    """Play an mp3: decode with miniaudio, play via sounddevice."""
    import numpy as np
    import sounddevice as sd

    import miniaudio

    decoded = miniaudio.decode_file(path)
    samples = np.array(decoded.samples, dtype=np.int16)
    if decoded.nchannels > 1:
        samples = samples.reshape(-1, decoded.nchannels)
    sd.play(samples, decoded.sample_rate)
    sd.wait()


def _temp_mp3_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"jarvo_tts_{uuid.uuid4().hex}.mp3")


def prepare(text: str, lang: str = "en") -> None:
    """Synthesize WITHOUT playing — warms up edge-tts's first-request cost
    at startup so the user's first real command speaks instantly."""
    _run_async(_synthesize(text, lang, config.MP3_PATH))


def speak(text: str, lang: str = "en") -> None:
    """Convert text to speech and play it (blocking). Safe to call from
    multiple threads at once — each call uses its own temp file and
    playback is serialized so voices never overlap or corrupt each other."""
    if not text:
        return
    last_err = None
    with _speak_lock:
        path = _temp_mp3_path()
        try:
            for attempt in range(2):
                try:
                    _run_async(_synthesize(text, lang, path))
                    _play(path)
                    return
                except Exception as e:
                    last_err = e
            raise last_err  # caller prints a fallback message
        finally:
            try:
                os.remove(path)
            except OSError:
                pass