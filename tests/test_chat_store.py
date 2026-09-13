"""Offline tests for chat_store (SQLite persistence layer)."""
import pytest

import chat_store


@pytest.fixture()
def store(tmp_path):
    chat_store.reset_for_tests(str(tmp_path / "test_saathi.db"))
    yield chat_store
    chat_store.reset_for_tests()  # restore default path


class TestSessions:
    def test_touch_creates_then_updates(self, store):
        store.touch_session("sess-aaaa")
        store.touch_session("sess-aaaa")  # upsert must not raise/duplicate
        with store._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert n == 1

    def test_sessions_are_independent(self, store):
        store.touch_session("sess-aaaa")
        store.touch_session("sess-bbbb")
        with store._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert n == 2


class TestMessages:
    def test_append_and_get_roundtrip(self, store):
        store.append_message("s1", "user", "salam")
        store.append_message("s1", "assistant", "Salam! Kaise hain aap?")
        hist = store.get_history("s1")
        assert hist == [
            {"role": "user", "content": "salam"},
            {"role": "assistant", "content": "Salam! Kaise hain aap?"},
        ]

    def test_sessions_do_not_mix(self, store):
        store.append_message("s1", "user", "sirf s1 ka message")
        store.append_message("s2", "user", "sirf s2 ka message")
        assert store.get_history("s1")[-1]["content"] == "sirf s1 ka message"
        assert store.get_history("s2")[-1]["content"] == "sirf s2 ka message"
        assert len(store.get_history("s1")) == 1

    def test_history_trimmed_to_limit(self, store):
        for i in range(20):
            store.append_message("s1", "user", f"msg {i}")
        hist = store.get_history("s1")
        assert len(hist) == store.HISTORY_LIMIT
        # newest kept, oldest dropped
        assert hist[-1]["content"] == "msg 19"

    def test_persists_across_reopen(self, store, tmp_path):
        store.append_message("s1", "user", "yaad rakhna")
        db_path = store.DB_PATH
        store._initialized = False  # simulate fresh module load
        store.DB_PATH = db_path
        assert store.get_history("s1")[-1]["content"] == "yaad rakhna"


class TestActivity:
    def test_record_and_get(self, store):
        store.record_activity("s1", "take_screenshot", "C:/shot.png", ok=True)
        items = store.get_activity("s1")
        assert items[0]["tool"] == "take_screenshot"
        assert items[0]["ok"] is True
        assert "t" in items[0]

    def test_detail_truncated_to_60(self, store):
        store.record_activity("s1", "open_app", "x" * 200)
        assert len(store.get_activity("s1")[0]["detail"]) == 60

    def test_failures_stored_as_not_ok(self, store):
        store.record_activity("s1", "send_whatsapp", "WhatsApp error: boom", ok=False)
        assert store.get_activity("s1")[0]["ok"] is False

    def test_capped_at_12(self, store):
        for i in range(20):
            store.record_activity("s1", f"tool{i}")
        assert len(store.get_activity("s1", limit=50)) == 12

    def test_sessions_separate(self, store):
        store.record_activity("s1", "tool_a")
        store.record_activity("s2", "tool_b")
        assert store.get_activity("s1")[0]["tool"] == "tool_a"
        assert store.get_activity("s2")[0]["tool"] == "tool_b"


class TestClearSession:
    def test_clears_messages_activity_and_row(self, store):
        store.touch_session("s1")
        store.append_message("s1", "user", "hello")
        store.record_activity("s1", "open_app")
        store.clear_session("s1")
        assert store.get_history("s1") == []
        assert store.get_activity("s1") == []
        with store._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM sessions WHERE session_id='s1'").fetchone()[0]
        assert n == 0

    def test_other_sessions_untouched(self, store):
        store.append_message("s1", "user", "keep me")
        store.append_message("s2", "user", "also keep me")
        store.record_activity("s1", "tool1")
        store.record_activity("s2", "tool2")
        store.clear_session("s1")
        assert [m["content"] for m in store.get_history("s2")] == ["also keep me"]
        assert store.get_activity("s2")[0]["tool"] == "tool2"
        assert store.get_history("s1") == []

    def test_clear_then_reuse_fresh(self, store):
        store.append_message("s1", "user", "old")
        store.clear_session("s1")
        store.append_message("s1", "user", "new")
        hist = store.get_history("s1")
        assert len(hist) == 1 and hist[0]["content"] == "new"
