"""Offline tests for stt.py pure logic (no network)."""
import io
import wave

import numpy as np

import stt


class TestWordFixes:
    def test_whatsapp_arabic_variants(self):
        assert stt._normalize("ویڈس ایپ pe message bhejo") == "WhatsApp pe message bhejo"

    def test_roman_mishears(self):
        assert stt._normalize("asep kholo") == "WhatsApp kholo"
        assert stt._normalize("wasap pe bhejo") == "WhatsApp pe bhejo"

    def test_youtube(self):
        assert stt._normalize("یوٹیوب kholo") == "YouTube kholo"

    def test_plain_text_untouched(self):
        assert stt._normalize("kya hal hai") == "kya hal hai"


class TestWavEncoding:
    def _encode(self, audio):
        data = stt._to_wav_bytes(audio)
        buf = io.BytesIO(data)
        with wave.open(buf, "rb") as wf:
            return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()

    def test_int16_mono_16k(self):
        audio = np.zeros(1600, dtype=np.int16)  # 0.1s
        ch, sw, fr, n = self._encode(audio)
        assert (ch, sw, fr) == (1, 2, 16000)
        assert n == 1600

    def test_stereo_downmixed(self):
        audio = np.zeros((800, 2), dtype=np.int16)
        _, _, _, n = self._encode(audio)
        assert n == 800


class TestContactNamesPrompt:
    def test_prompt_built_without_error(self):
        assert isinstance(stt._ROMAN_PROMPT, str)
        assert len(stt._ROMAN_PROMPT) <= 890
