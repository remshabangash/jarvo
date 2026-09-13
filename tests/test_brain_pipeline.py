"""Offline tests for the brain.think() pipeline using a FAKE Groq client.

No network: we monkeypatch brain._client with an object that returns
scripted LLM responses, so the full dispatch logic (tool calls, WhatsApp
staging/confirmation, email staging, capture fast-path) is exercised
exactly as it runs in production.
"""
import json
import types

import pytest

import brain
import executor  # noqa: F401  (registers brain._executor)


# ---------------- Fake Groq client ----------------

class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeToolCall:
    def __init__(self, name, args):
        self.function = types.SimpleNamespace(name=name, arguments=json.dumps(args))


class _FakeResponse:
    def __init__(self, message):
        self.choices = [types.SimpleNamespace(message=message)]


class FakeGroqClient:
    """Returns queued responses in order; records every request it sees."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)

    # groq SDK surface used by brain._complete()
    @property
    def completions(self):
        return self

    class _ChatNS:
        pass


def _make_client(responses):
    """Build a fake client matching the attribute path brain uses:
    _client.chat.completions.create(...)"""
    inner = FakeGroqClient(responses)

    class _Completions:
        def create(self, **kwargs):
            return inner.chat(**kwargs)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

        def __init__(self):
            self._inner = inner

        @property
        def calls(self):
            return self._inner.calls

    return _Client()


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    """Install a fresh fake client before every test; restore afterwards."""
    client = _make_client([])
    monkeypatch.setattr(brain, "_client", client)
    brain._pending_whatsapp.clear()
    yield client
    brain._pending_whatsapp.clear()


def _queue(client, *messages):
    client._inner._responses = list(messages)


# ---------------- General reply path ----------------

class TestGeneralReply:
    def test_plain_text_reply(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(content="Salam! Sab theek hai.")))
        assert brain.think("salam") == "Salam! Sab theek hai."

    def test_general_reply_tool(self, _patch_client):
        _queue(_patch_client, _FakeResponse(
            _FakeMessage(tool_calls=[_FakeToolCall("general_reply", {"reply": "Main theek hoon!"})])))
        assert brain.think("aap kaise ho") == "Main theek hoon!"

    def test_no_content_falls_back(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(content=None)))
        assert brain.think("hello") == "..."


# ---------------- WhatsApp staging & confirmation ----------------

class TestWhatsAppStateMachine:
    def test_stages_confirmation_question(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_whatsapp", {"contact": "Ali", "message": "hello", "speak": "Ali ko 'hello' bhej doon?"})])))
        reply = brain.think("Ali ko hello bhejo")
        assert "Ali" in reply and "?" in reply
        assert brain._pending_whatsapp["contact"] == "Ali"

    def test_fast_yes_sends_staged_message(self, _patch_client, monkeypatch):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_whatsapp", {"contact": "Ali", "message": "hello", "speak": "bhej doon?"})])))
        brain.think("Ali ko hello bhejo")

        sent = {}
        monkeypatch.setattr(brain, "_execute_and_reply", lambda name, args: sent.update(args) or "ho gaya")
        assert brain.think("haan") == "ho gaya"
        assert sent == {"contact": "Ali", "message": "hello"}
        assert not brain._pending_whatsapp  # cleared after send

    def test_fast_no_cancels(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_whatsapp", {"contact": "Ali", "message": "hello", "speak": "bhej doon?"})])))
        brain.think("Ali ko hello bhejo")
        assert brain.think("nahi") == "Theek hai, message cancel kar diya."
        assert not brain._pending_whatsapp

    def test_empty_message_asks_what_to_write(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_whatsapp", {"contact": "Ali", "message": "", "speak": "kya bhejna hai?"})])))
        reply = brain.think("Ali ko message bhejo")
        assert "kya" in reply.lower()
        assert brain._pending_whatsapp["message"] is None

    def test_speech_extraction_fills_empty_message(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_whatsapp", {"contact": "Ali", "message": "", "speak": "bhej doon?"})])))
        reply = brain.think("Ali ko main ghar aa raha hoon bhejo")
        assert "'main ghar aa raha hoon'" in reply
        assert brain._pending_whatsapp["message"] == "main ghar aa raha hoon"


# ---------------- Cancel tool ----------------

class TestCancelSend:
    def test_cancel_clears_pending(self, _patch_client):
        brain._pending_whatsapp.update({"contact": "Ali", "message": "hi"})
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("cancel_send", {"speak": "Cancel kar diya."})])))
        assert brain.think("rehne do") == "Cancel kar diya."
        assert not brain._pending_whatsapp


# ---------------- Email staging ----------------

class TestEmailStaging:
    def test_email_staged_with_question(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_email", {"to": "remsha", "subject": "", "body": "",
                                         "speak": "Remsha ko email bhej doon?"})])))
        assert brain.think("remsha ko email bhejo") == "Remsha ko email bhej doon?"
        assert brain._pending_whatsapp["kind"] == "email"
        assert brain._pending_whatsapp["to"] == "remsha"

    def test_email_without_recipient_asks(self, _patch_client):
        _queue(_patch_client, _FakeResponse(_FakeMessage(tool_calls=[
            _FakeToolCall("send_email", {"to": "", "subject": "", "body": "", "speak": ""})])))
        assert "kisko" in brain.think("email bhejo").lower()


# ---------------- Capture fast-path ----------------

class TestCaptureFastPath:
    def test_screenshot_bypasses_llm_dispatch(self, _patch_client, monkeypatch):
        # Even if the LLM answered plain text, the capture intent forces the tool
        _queue(_patch_client, _FakeResponse(_FakeMessage(content="...")))
        monkeypatch.setattr(brain, "_executor", lambda name, args: "C:/shots/x.png")
        assert brain.think("screenshot le lo") == "Screenshot le liya."

    def test_recording_start(self, _patch_client, monkeypatch):
        _queue(_patch_client, _FakeResponse(_FakeMessage(content="...")))
        monkeypatch.setattr(brain, "_executor", lambda name, args: "C:/vid/x.mp4")
        assert brain.think("recording shuru karo") == "Recording shuru kar di hai."


# ---------------- Error handling ----------------

class TestModelFallback:
    def test_rate_limit_switches_to_fallback_model(self, _patch_client, monkeypatch):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            if kwargs.get("model") == brain.config.GROQ_MODEL:
                raise Exception("Error 429: rate limit exceeded")
            return _FakeResponse(_FakeMessage(content="Fallback se jawab."))

        monkeypatch.setattr(brain._client.chat.completions, "create", create)
        assert brain.think("salam") == "Fallback se jawab."
        assert calls[0]["model"] == brain.config.GROQ_MODEL
        assert calls[-1]["model"] == brain.config.FALLBACK_MODEL
