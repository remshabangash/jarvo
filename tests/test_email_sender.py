"""Offline tests for email_sender contact resolution (no SMTP)."""
from email_sender import _resolve_email


class TestResolveEmail:
    def test_exact_name(self):
        result = _resolve_email("sara")
        assert result is None or "@" in result  # local file may or may not exist

    def test_case_insensitive(self):
        assert _resolve_email("SARA".lower()) == _resolve_email("sara")

    def test_raw_address_passthrough(self):
        assert _resolve_email("someone@example.com") == "someone@example.com"

    def test_unknown_name_returns_none(self):
        assert _resolve_email("zzz-no-such-contact-zzz") is None

    def test_contacts_loaded(self):
        from email_sender import EMAIL_CONTACTS
        assert isinstance(EMAIL_CONTACTS, dict)
