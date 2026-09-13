"""Offline tests for main.py helpers (no mic, no TTS, no API)."""
from main import detect_script


class TestDetectScript:
    def test_pashto_letters(self):
        assert detect_script("ږ") == "ps"

    def test_urdu_script(self):
        assert detect_script("خداحافظ") == "ur"

    def test_english(self):
        assert detect_script("hello there") == "en"

    def test_fallback_is_english(self):
        assert detect_script("12345") == "en"

    def test_mixed_urdu_wins_over_english(self):
        # Urdu-script char anywhere -> Urdu voice
        assert detect_script("ok خداحافظ") == "ur"
