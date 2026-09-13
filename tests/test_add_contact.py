"""Offline tests for the voice add_contact feature (save flows + pipeline)."""
import json

import pytest

import brain
import executor  # registers brain._executor


@pytest.fixture
def contacts_env(tmp_path, monkeypatch):
    """Point both contact files at throwaway paths."""
    import whatsapp_bot
    import email_sender

    wa_file = tmp_path / "contacts.json"
    em_file = tmp_path / "email_contacts.json"
    monkeypatch.setattr(whatsapp_bot, "CONTACTS_FILE", str(wa_file))
    monkeypatch.setattr(email_sender, "_CONTACTS_FILE", str(em_file))
    monkeypatch.setattr(email_sender, "EMAIL_CONTACTS", {"sara": "old@example.com"})
    return {"wa": wa_file, "em": em_file}


class TestSaveContactPhone:
    def test_saves_valid_number(self, contacts_env):
        from whatsapp_bot import save_contact
        result = save_contact("Ali", "923001234567")
        assert result.startswith("Contact saved")
        data = json.loads(contacts_env["wa"].read_text(encoding="utf-8"))
        assert data["Ali"]["phone"] == "923001234567"

    def test_strips_non_digits(self, contacts_env):
        from whatsapp_bot import save_contact
        save_contact("Ali", "+92 300-1234567")
        data = json.loads(contacts_env["wa"].read_text(encoding="utf-8"))
        assert data["Ali"]["phone"] == "923001234567"

    def test_rejects_short_number(self, contacts_env):
        from whatsapp_bot import save_contact
        assert save_contact("Ali", "123").startswith("Error")

    def test_rejects_empty_name(self, contacts_env):
        from whatsapp_bot import save_contact
        assert save_contact("", "923001234567").startswith("Error")

    def test_overwrite_preserves_other_entries(self, contacts_env):
        from whatsapp_bot import save_contact
        save_contact("First", "923001111111")
        save_contact("Second", "923002222222")
        save_contact("First", "923003333333")  # update
        data = json.loads(contacts_env["wa"].read_text(encoding="utf-8"))
        assert data["First"]["phone"] == "923003333333"
        assert data["Second"]["phone"] == "923002222222"

    def test_saved_contact_resolves(self, contacts_env):
        from whatsapp_bot import save_contact, resolve_contact
        save_contact("Bilal", "92300999888", aliases=["billu"])
        name, phone = resolve_contact("bilal")
        assert name == "Bilal" and phone == "92300999888"


class TestSaveEmailContact:
    def test_saves_valid_address(self, contacts_env):
        import email_sender
        from email_sender import save_email_contact
        result = save_email_contact("Sara", "sara@example.com")
        assert result.startswith("Email contact saved")
        data = json.loads(contacts_env["em"].read_text(encoding="utf-8"))
        assert data["sara"] == "sara@example.com"
        assert email_sender.EMAIL_CONTACTS["sara"] == "sara@example.com"  # refreshed

    def test_rejects_bad_address(self, contacts_env):
        from email_sender import save_email_contact
        assert save_email_contact("Sara", "not-an-email").startswith("Error")

    def test_resolution_uses_new_contact(self, contacts_env):
        from email_sender import save_email_contact, _resolve_email
        save_email_contact("Sara", "sara@example.com")
        assert _resolve_email("Sara") == "sara@example.com"


class TestExecutorTool:
    def test_phone_dispatches_to_whatsapp_store(self, contacts_env):
        result = executor._add_contact_tool({"name": "Ali", "phone": "923001234567"})
        assert "Contact saved" in result

    def test_email_dispatches_to_email_store(self, contacts_env):
        result = executor._add_contact_tool({"name": "Ali", "email": "ali@x.com"})
        assert "Email contact saved" in result

    def test_both_saved_at_once(self, contacts_env):
        result = executor._add_contact_tool(
            {"name": "Ali", "phone": "923001234567", "email": "ali@x.com"})
        assert "Contact saved" in result and "Email contact saved" in result

    def test_no_details_fails_cleanly(self, contacts_env):
        assert executor._add_contact_tool({"name": "Ali"}).startswith("Error")


class TestBrainPipeline:
    @pytest.fixture(autouse=True)
    def _fake_llm(self, monkeypatch, contacts_env):
        """Fake Groq client + throwaway contact files for pipeline tests."""
        import types

        class _Msg:
            def __init__(self, content=None, tool_calls=None):
                self.content, self.tool_calls = content, tool_calls

        class _Resp:
            def __init__(self, msg):
                self.choices = [types.SimpleNamespace(message=msg)]

        class _Completions:
            next_response = None

            def create(self, **kwargs):
                return type(self).next_response

        class _Client:
            chat = types.SimpleNamespace(completions=_Completions())

        self._Msg, self._Resp = _Msg, _Resp
        self._Completions = _Completions
        self.wa_file = contacts_env["wa"]
        monkeypatch.setattr(brain, "_client", _Client())
        brain._pending_whatsapp.clear()
        yield
        brain._pending_whatsapp.clear()

    def _queue(self, tool_name, args):
        import types
        call = types.SimpleNamespace(
            function=types.SimpleNamespace(name=tool_name,
                                           arguments=json.dumps(args)))
        self._Completions.next_response = self._Resp(self._Msg(tool_calls=[call]))

    def test_stages_confirmation_with_digits(self):
        self._queue("add_contact", {"name": "Ali", "phone": "923001234567", "speak": ""})
        reply = brain.think("Ali ka number save karo 923001234567")
        assert "923001234567" in reply and "?" in reply
        assert brain._pending_whatsapp["kind"] == "contact"

    def test_yes_commits_save(self):
        self._queue("add_contact", {"name": "Ali", "phone": "923001234567", "speak": ""})
        brain.think("Ali ka number save karo 923001234567")
        reply = brain.think("haan")
        assert "Save ho gaya" in reply
        data = json.loads(self.wa_file.read_text(encoding="utf-8"))
        assert data["Ali"]["phone"] == "923001234567"
        assert not brain._pending_whatsapp

    def test_no_cancels(self):
        self._queue("add_contact", {"name": "Ali", "phone": "923001234567", "speak": ""})
        brain.think("Ali ka number save karo 923001234567")
        assert brain.think("nahi") == "Theek hai, save cancel kar diya."
        assert not brain._pending_whatsapp

    def test_no_details_asks(self):
        self._queue("add_contact", {"name": "Ali", "phone": "", "email": "", "speak": ""})
        reply = brain.think("Ali ko save karo")
        assert "number ya email" in reply
        assert not brain._pending_whatsapp
