"""Offline tests for brain.py pure logic (no API calls)."""
import brain


class TestExtractMessage:
    def test_basic(self):
        assert brain._extract_message("Ahmed ko hello bhejo", "Ahmed") == "hello"

    def test_multiword(self):
        assert brain._extract_message("Ali ko main aa raha hoon likh do", "Ali") == "main aa raha hoon"

    def test_generic_word_is_not_a_message(self):
        assert brain._extract_message("Ali ko message bhejo", "Ali") is None

    def test_wrong_contact_returns_none(self):
        assert brain._extract_message("Ahmed ko hello bhejo", "Sara") is None

    def test_no_text_said(self):
        assert brain._extract_message("Ali ko bhejo", "Ali") is None


class TestScriptOf:
    def test_roman_urdu(self):
        assert brain._script_of("yeh kya hai") == "ur"

    def test_roman_urdu_question(self):
        assert brain._script_of("aap kaise ho") == "ur"

    def test_urdu_script(self):
        assert brain._script_of("خداحافظ") == "ur"

    def test_english(self):
        assert brain._script_of("take a screenshot please") == "en"


class TestCaptureIntent:
    def test_screenshot(self):
        assert brain._capture_intent("screenshot le lo") == "screenshot"

    def test_start_recording(self):
        assert brain._capture_intent("screen record karo") == "start"

    def test_message_not_capture(self):
        assert brain._capture_intent("Ahmed ko message bhejo") is None


class TestRateLimit:
    def test_detects_429(self):
        assert brain._is_rate_limit(Exception("Error 429: Too Many Requests")) is True

    def test_other_error(self):
        assert brain._is_rate_limit(Exception("connection refused")) is False


class TestExecutorWiring:
    def test_executor_registered(self):
        import executor  # noqa: F401
        assert brain._executor is not None
