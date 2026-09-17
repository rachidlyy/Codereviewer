"""Application configuration.

All settings come from environment variables, optionally loaded from a
`.env` file at the backend root. Nothing here requires a database or any
external service to be present: the app degrades gracefully when the LLM
key is missing.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Load .env once at import time. Existing environment variables win.
load_dotenv(BACKEND_ROOT / ".env")


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- LLM ------------------------------------------------------------------

#: Gemini API key. When empty, the AI reviewer falls back to a deterministic
#: local reviewer so the demo still works end to end.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()

#: Gemini model used for reviews. Override with GEMINI_MODEL if your key
#: does not have access to the default.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

GEMINI_API_URL: str = os.getenv(
    "GEMINI_API_URL",
    "https://generativelanguage.googleapis.com/v1beta",
).rstrip("/")

#: Request timeout for the LLM call, in seconds.
LLM_TIMEOUT_SECONDS: float = _get_float("LLM_TIMEOUT_SECONDS", 45.0)

#: Sampling temperature for the LLM.
LLM_TEMPERATURE: float = _get_float("LLM_TEMPERATURE", 0.25)


def llm_enabled() -> bool:
    """True when a real LLM call can be attempted."""
    return bool(GEMINI_API_KEY)


# --- Code execution -------------------------------------------------------

#: Per-test-case execution timeout, in seconds. Each test case runs in its
#: own subprocess so one slow test cannot poison the others.
TEST_TIMEOUT_SECONDS: float = _get_float("TEST_TIMEOUT_SECONDS", 3.0)

#: Hard ceiling for the whole submission, in seconds.
SUBMISSION_TIMEOUT_SECONDS: float = _get_float("SUBMISSION_TIMEOUT_SECONDS", 20.0)

#: Python interpreter used to execute student code. Defaults to the
#: interpreter running the API server.
PYTHON_EXECUTABLE: str = os.getenv("PYTHON_EXECUTABLE", "").strip()


# --- Server ---------------------------------------------------------------

#: Comma-separated list of allowed CORS origins.
CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

#: When true, the API exposes extra debug detail (e.g. raw student output).
DEBUG: bool = _get_bool("DEBUG", False)
