"""SQLite-backed chat history + activity log for the web server.

Replaces the old in-memory `history = []` / `activity_log = []` lists, which
were lost on every server restart and mixed together when several devices
talked to the server at once.

Design:
- One sessions row per browser (session id generated client-side, arrives in
  the X-Session-Id header) — per-device history separation.
- messages: the LLM context (capped at the same 10-turn window the server
  used before) — survives restarts, so the assistant remembers the
  conversation across server restarts and page reloads.
- activity: last tool runs per session for the UI activity strip.

Only the Python stdlib (sqlite3) — no new dependencies. Thread-safe: one
connection per operation, WAL mode for concurrent readers/writers.
"""
import os
import sqlite3
import threading
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saathi.db")

# Same window size the old in-memory history used (del history[:-10]).
HISTORY_LIMIT = 10

_init_lock = threading.Lock()
_initialized = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role     TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content  TEXT NOT NULL,
    ts       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    ok         INTEGER NOT NULL DEFAULT 1,
    ts         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_session ON activity(session_id, id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _close(conn: sqlite3.Connection) -> None:
    """Always close: sqlite3's `with` only wraps the TRANSACTION, not the
    connection — unclosed handles leak and keep WAL files locked (a real
    problem on Windows where open handles block file deletion)."""
    try:
        conn.commit()
    finally:
        conn.close()


def _init() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _initialized = True


def reset_for_tests(path: str | None = None) -> None:
    """Test helper: point the module at a fresh throwaway DB."""
    global DB_PATH, _initialized
    if path is not None:
        DB_PATH = path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    _initialized = False
    _init()


# ---------------- Sessions ----------------

def touch_session(session_id: str) -> None:
    """Upsert the session row (created_at on first sight, last_seen always)."""
    _init()
    now = int(time.time())
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, created_at, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET last_seen=excluded.last_seen",
            (session_id, now, now),
        )
    finally:
        _close(conn)


# ---------------- Messages (LLM context) ----------------

def append_message(session_id: str, role: str, content: str) -> None:
    _init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, content, int(time.time())),
        )
    finally:
        _close(conn)
    _trim_history(session_id)


def _trim_history(session_id: str) -> None:
    """Keep only the last HISTORY_LIMIT messages per session (same 5-exchange
    window the in-memory version kept via `del history[:-10]`)."""
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND id NOT IN "
            "(SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?)",
            (session_id, session_id, HISTORY_LIMIT),
        )
    finally:
        _close(conn)


def get_history(session_id: str) -> list[dict]:
    """LLM context for this session, oldest first: [{'role','content'}, ...]."""
    _init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    finally:
        _close(conn)
    return [{"role": r, "content": c} for r, c in rows]


# ---------------- Activity strip ----------------

def record_activity(session_id: str, tool: str, detail: str = "", ok: bool = True) -> None:
    _init()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO activity (session_id, tool, detail, ok, ts) VALUES (?, ?, ?, ?, ?)",
            (session_id, tool, (detail or "")[:60], 1 if ok else 0, int(time.time())),
        )
        # keep the strip small — last 12 per session
        conn.execute(
            "DELETE FROM activity WHERE session_id = ? AND id NOT IN "
            "(SELECT id FROM activity WHERE session_id = ? ORDER BY id DESC LIMIT 12)",
            (session_id, session_id),
        )
    finally:
        _close(conn)


def clear_session(session_id: str) -> None:
    """Remove a session's history, activity, and row ("New chat" button).
    Other sessions are untouched."""
    _init()
    conn = _connect()
    try:
        for table in ("messages", "activity", "sessions"):
            conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
    finally:
        _close(conn)


def get_activity(session_id: str, limit: int = 6) -> list[dict]:
    """Last `limit` tool runs for the session, oldest first (matches the old
    activity_log[-6:] shape the UI expects: {tool, detail, ok, t})."""
    _init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT tool, detail, ok, ts FROM activity WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    finally:
        _close(conn)
    return [{"tool": t, "detail": d, "ok": bool(o), "t": ts} for t, d, o, ts in rows]
