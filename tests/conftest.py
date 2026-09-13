"""Shared test setup: make project imports work and keep tests 100% offline.

- Adds the project root to sys.path (tests live in saathi_assistant/tests/).
- Seeds dummy API keys BEFORE any module imports a Groq client, so no test
  ever needs (or touches) the real network. Any accidental API call would
  fail with an auth error instead of burning quota.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("GROQ_API_KEY", "gsk-DUMMY-KEY-FOR-TESTS")
os.environ.setdefault("GROQ_API_KEY_STT", "gsk-DUMMY-KEY-FOR-TESTS")
