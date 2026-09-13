"""Offline tests for the Gemini STT engine + the stt.transcribe dispatch.

All network calls are mocked (_post / transcribe_wav_bytes monkeypatched) —
nothing here ever touches Google or Groq.
"""
import urllib.error

import pytest

import config
import stt
import stt_gemini


class TestBuildInstruction:
    def test_contains_verbatim_rules(self):
        instr = stt_gemini._build_instruction()
        assert "EXACT" in instr
        assert "WhatsApp" in instr

    def test_roman_urdu_mode_uses_latin_letters(self):
        stt_gemini.ROMAN_URDU_MODE = True
        try:
            assert "Latin letters" in stt_gemini._build_instruction()
        finally:
            stt_gemini.ROMAN_URDU_MODE = True

    def test_vocab_hint_included(self, monkeypatch):
        monkeypatch.setattr(stt_gemini, "_VOCAB_HINT", "Ahmed, Sara")
        assert "Ahmed, Sara" in stt_gemini._build_instruction()


class TestTranscribeWavBytes:
    def _fake_response(self):
        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": "kya hal hai"}]},
                    "speechResult": {"languageCode": "ur-PK"},
                }
            ]
        }

    def test_success_returns_text_and_lang(self, monkeypatch):
        monkeypatch.setattr(stt_gemini, "_post", lambda url, body, timeout=30.0: self._fake_response())
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        text, lang = stt_gemini.transcribe_wav_bytes(b"fake-wav")
        assert text == "kya hal hai"
        assert lang == "ur"

    def test_request_body_shape(self, monkeypatch):
        captured = {}

        def fake_post(url, body, timeout=30.0):
            captured["url"] = url
            captured["body"] = body
            return self._fake_response()

        monkeypatch.setattr(stt_gemini, "_post", fake_post)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        stt_gemini.transcribe_wav_bytes(b"fake-wav")

        assert "gemini-3.5-transcribe" in captured["url"]
        assert "key=fake-key" in captured["url"]
        inline = captured["body"]["contents"][0]["parts"][0]["inline_data"]
        assert inline["mime_type"].startswith("audio/wav")
        assert inline["data"]  # base64 payload present
        assert "system_instruction" in captured["body"]

    def test_no_key_raises(self, monkeypatch):
        monkeypatch.setattr(config, "GEMINI_API_KEY", None)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            stt_gemini.transcribe_wav_bytes(b"fake-wav")

    def test_http_error_propagates_immediately(self, monkeypatch):
        err = urllib.error.HTTPError("url", 400, "bad", None, None)  # not retryable

        def fake_post(url, body, timeout=30.0):
            raise err

        monkeypatch.setattr(stt_gemini, "_post", fake_post)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        with pytest.raises(urllib.error.HTTPError):
            stt_gemini.transcribe_wav_bytes(b"fake-wav")

    def test_retryable_error_then_success(self, monkeypatch):
        calls = {"n": 0}
        sleeps = []

        def fake_post(url, body, timeout=30.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError("url", 503, "busy", None, None)
            return self._fake_response()

        monkeypatch.setattr(stt_gemini, "_post", fake_post)
        monkeypatch.setattr(stt_gemini.time, "sleep", sleeps.append)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        text, _ = stt_gemini.transcribe_wav_bytes(b"fake-wav")
        assert text == "kya hal hai"
        assert calls["n"] == 2
        assert len(sleeps) == 1  # one backoff between the two attempts

    def test_empty_transcript_raises(self, monkeypatch):
        empty = {"candidates": [{"content": {"parts": [{"text": ""}]}}]}
        monkeypatch.setattr(stt_gemini, "_post", lambda url, body, timeout=30.0: empty)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        with pytest.raises(RuntimeError, match="empty"):
            stt_gemini.transcribe_wav_bytes(b"fake-wav")

    def test_malformed_response_raises(self, monkeypatch):
        monkeypatch.setattr(stt_gemini, "_post", lambda url, body, timeout=30.0: {})
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        with pytest.raises(RuntimeError, match="response shape"):
            stt_gemini.transcribe_wav_bytes(b"fake-wav")

    def test_missing_language_metadata_falls_back_to_en(self, monkeypatch):
        no_speech = {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}
        monkeypatch.setattr(stt_gemini, "_post", lambda url, body, timeout=30.0: no_speech)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        _, lang = stt_gemini.transcribe_wav_bytes(b"fake-wav")
        assert lang == "en"


class TestDispatch:
    """stt.transcribe() routing between Gemini and Whisper."""

    @pytest.fixture(autouse=True)
    def restore_provider(self):
        yield
        config.STT_PROVIDER = "auto"

    def _patch_audio(self, monkeypatch):
        monkeypatch.setattr(stt, "_to_wav_bytes", lambda audio: b"fake-wav")

    def test_auto_without_key_uses_whisper(self, monkeypatch):
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", None)
        monkeypatch.setattr(config, "STT_PROVIDER", "auto")
        called = []
        monkeypatch.setattr(stt, "_whisper_transcribe", lambda a: called.append(1) or ("wh text", "en"))
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: (_ for _ in ()).throw(AssertionError("gemini must not run")))
        assert stt.transcribe(object()) == ("wh text", "en")
        assert called == [1]

    def test_auto_with_key_prefers_gemini(self, monkeypatch):
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(config, "STT_PROVIDER", "auto")
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: ("gem text", "en"))
        monkeypatch.setattr(stt, "_whisper_transcribe", lambda a: (_ for _ in ()).throw(AssertionError("whisper must not run")))
        assert stt.transcribe(object()) == ("gem text", "en")

    def test_auto_falls_back_to_whisper_on_gemini_error(self, monkeypatch):
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(config, "STT_PROVIDER", "auto")
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: (_ for _ in ()).throw(RuntimeError("google down")))
        monkeypatch.setattr(stt, "_whisper_transcribe", lambda a: ("wh text", "en"))
        assert stt.transcribe(object()) == ("wh text", "en")

    def test_gemini_provider_raises_when_gemini_fails(self, monkeypatch):
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(config, "STT_PROVIDER", "gemini")
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            stt.transcribe(object())

    def test_whisper_provider_skips_gemini(self, monkeypatch):
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(config, "STT_PROVIDER", "whisper")
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: (_ for _ in ()).throw(AssertionError("gemini must not run")))
        monkeypatch.setattr(stt, "_whisper_transcribe", lambda a: ("wh text", "en"))
        assert stt.transcribe(object()) == ("wh text", "en")

    def test_gemini_output_normalized(self, monkeypatch):
        """Gemini text goes through the same _WORD_FIXES (WhatsApp etc.)."""
        self._patch_audio(monkeypatch)
        monkeypatch.setattr(config, "GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(config, "STT_PROVIDER", "auto")
        monkeypatch.setattr(stt._gemini, "transcribe_wav_bytes", lambda w: ("wasap pe bhejo", "en"))
        text, _ = stt.transcribe(object())
        assert text == "WhatsApp pe bhejo"


class TestAvailable:
    def test_available_reflects_key(self, monkeypatch):
        monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
        assert stt_gemini.available() is True
        monkeypatch.setattr(config, "GEMINI_API_KEY", None)
        assert stt_gemini.available() is False
