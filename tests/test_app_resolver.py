"""Offline tests for app_resolver (no app is actually launched)."""
import sys

import app_resolver
from app_resolver import _common


class TestLooksLikeDomain:
    def test_simple_domain(self):
        assert _common.looks_like_domain("example.com") is True

    def test_multi_tld(self):
        assert _common.looks_like_domain("mail.google.co.uk") is True

    def test_spaces_reject(self):
        assert _common.looks_like_domain("my app") is False

    def test_no_dot_reject(self):
        assert _common.looks_like_domain("notepad") is False


class TestSharedTables:
    def test_youtube_in_url_map(self):
        assert "youtube" in _common.URL_APPS

    def test_whatsapp_variants_covered(self):
        for k in ("whatsapp", "asep", "asap", "wasap"):
            assert k in _common.URL_APPS

    def test_not_an_app_guard(self):
        for k in ("screenshot", "message", "recording"):
            assert k in _common.NOT_AN_APP


class TestPlatformSelection:
    def test_correct_module_for_platform(self):
        expected = "windows" if sys.platform == "win32" else (
            "macos" if sys.platform == "darwin" else "linux")
        assert app_resolver.resolve_and_open.__module__.endswith(expected)


class TestExecutorDelegation:
    def test_executor_uses_resolver(self, monkeypatch):
        # Stub the resolver so no real app/browser launch happens on any OS.
        import executor
        seen = {}

        def fake_resolve(name):
            seen["name"] = name
            return f"RESOLVED:{name}"

        monkeypatch.setattr(app_resolver, "resolve_and_open", fake_resolve)
        assert executor.open_app("anything") == "RESOLVED:anything"
        assert seen["name"] == "anything"
