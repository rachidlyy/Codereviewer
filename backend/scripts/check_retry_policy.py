"""Offline checks for the Gemini retry policy in ``app.services.ai_reviewer``.

These run against ``httpx.MockTransport``, so they need no API key, no network
and spend no quota - the error bodies below were captured from the live API
and are replayed verbatim.

    cd backend
    .venv/Scripts/python.exe scripts/check_retry_policy.py

The distinction under test is the one that caused a real bug: Google returns
503 for transient capacity (worth retrying with backoff) but 429 for a spent
per-minute quota (not worth retrying at 1s). The 429 body states the real wait
in ``error.details[].retryDelay`` and sends **no** ``Retry-After`` header.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Allow running this file from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.services import ai_reviewer as reviewer  # noqa: E402

#: Snapshot the genuine client before any patching. ``reviewer.httpx`` IS the
#: global httpx module, so assigning to ``reviewer.httpx.AsyncClient`` mutates
#: it process-wide - capturing the "real" one inside the patch helper would
#: instead capture the previous patch, and every later case would silently
#: reuse the first handler.
REAL_ASYNC_CLIENT = httpx.AsyncClient

# Captured verbatim from a live 429.
BODY_429 = {
    "error": {
        "code": 429,
        "message": (
            "You exceeded your current quota, please check your plan and billing "
            "details. For more information on this error, head to: "
            "https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your "
            "current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded "
            "for metric: generativelanguage.googleapis.com/"
            "generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\n"
            "Please retry in 50.713951557s."
        ),
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [
                    {
                        "quotaMetric": "generativelanguage.googleapis.com/"
                        "generate_content_free_tier_requests",
                        "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                        "quotaValue": "5",
                    }
                ],
            },
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "50s"},
        ],
    }
}

# Captured verbatim from a live 503.
BODY_503 = {
    "error": {
        "code": 503,
        "message": "This model is currently experiencing high demand. Spikes in demand "
        "are usually temporary. Please try again later.",
        "status": "UNAVAILABLE",
    }
}

OK_BODY = {
    "candidates": [
        {"content": {"parts": [{"text": '{"overall_score": 7}'}], "role": "model"}}
    ]
}

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name} - {detail}")


def call_with(handler) -> tuple[float, str, float | None, int]:
    """Run ``_call_llm`` against a mock handler.

    Returns ``(elapsed, message, retry_after, attempts)``. ``message`` is
    ``"OK"`` on success.
    """
    attempts = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return handler(request)

    transport = httpx.MockTransport(counting)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    original = reviewer.httpx.AsyncClient
    reviewer.httpx.AsyncClient = factory
    started = time.perf_counter()
    try:
        asyncio.run(reviewer._call_llm("test prompt"))
        return time.perf_counter() - started, "OK", None, attempts["n"]
    except reviewer.ReviewUnavailable as exc:
        return time.perf_counter() - started, str(exc), exc.retry_after, attempts["n"]
    finally:
        reviewer.httpx.AsyncClient = original


def with_retry_delay(seconds: str) -> dict:
    """The captured 429 body, with the stated wait replaced."""
    body = {"error": dict(BODY_429["error"])}
    body["error"]["details"] = [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": seconds}
    ]
    return body


def main() -> int:
    print("\n=== retry-delay extraction ===")

    delay = reviewer._server_retry_delay(httpx.Response(429, json=BODY_429))
    record(
        PASS if delay == 50.0 else FAIL,
        "reads RetryInfo.retryDelay from the body",
        f"got {delay!r} (want 50.0)",
    )

    header = httpx.Response(429, headers={"Retry-After": "12"}, json={})
    record(
        PASS if reviewer._server_retry_delay(header) == 12.0 else FAIL,
        "reads a Retry-After header when present",
        f"got {reviewer._server_retry_delay(header)!r}",
    )

    record(
        PASS if reviewer._server_retry_delay(httpx.Response(503, json=BODY_503)) is None
        else FAIL,
        "returns None when the provider states no wait",
        "503 body carries no RetryInfo",
    )

    print("\n=== error message quality ===")
    described = reviewer._describe_http_error(httpx.Response(429, json=BODY_429))
    record(
        PASS if "limit: 5" in described else FAIL,
        "keeps the quota detail at the end of the message",
        f"{len(described)} chars, names the limit: {'limit: 5' in described}",
    )
    record(
        PASS if "You exceeded your current quota" in described else FAIL,
        "keeps the human-readable summary",
        described[:100] + " ...",
    )

    print("\n=== behaviour under failure ===")

    elapsed, msg, hint, n = call_with(lambda req: httpx.Response(429, json=BODY_429))
    record(
        PASS if elapsed < 2.0 and n == 1 else FAIL,
        "429 stating a 50s wait fails fast",
        f"{elapsed:.2f}s after {n} attempt(s) - must not sleep 50s",
    )
    record(
        PASS if hint == 50.0 else FAIL,
        "429 exposes retry_after so the route can say how long",
        f"retry_after={hint!r}",
    )

    state = {"n": 0}

    def short_wait(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, json=with_retry_delay("2s"))
        return httpx.Response(200, json=OK_BODY)

    elapsed, msg, _, n = call_with(short_wait)
    record(
        PASS if msg == "OK" and n == 2 else FAIL,
        "429 stating a 2s wait is honoured and retried",
        f"{elapsed:.2f}s, {n} attempt(s), outcome={msg[:40]}",
    )
    record(
        PASS if 1.8 <= elapsed <= 4.0 else FAIL,
        "the 2s wait was actually slept",
        f"{elapsed:.2f}s",
    )

    elapsed, msg, _, n = call_with(lambda req: httpx.Response(503, json=BODY_503))
    record(
        PASS if n == config.LLM_MAX_ATTEMPTS else FAIL,
        "503 exhausts every attempt",
        f"{n} attempt(s), LLM_MAX_ATTEMPTS={config.LLM_MAX_ATTEMPTS}",
    )
    record(
        PASS if 2.5 <= elapsed <= 6.0 else FAIL,
        "503 uses exponential backoff (1s + 2s)",
        f"{elapsed:.2f}s",
    )

    elapsed, msg, _, n = call_with(
        lambda req: httpx.Response(
            400, json={"error": {"code": 400, "message": "API key not valid"}}
        )
    )
    record(
        PASS if n == 1 and elapsed < 1.0 else FAIL,
        "400 is never retried",
        f"{n} attempt(s) in {elapsed:.2f}s",
    )
    record(
        PASS if "API key not valid" in msg else FAIL,
        "400 preserves the provider message",
        msg[:100],
    )

    elapsed, msg, _, n = call_with(lambda req: httpx.Response(200, json=OK_BODY))
    record(
        PASS if msg == "OK" and n == 1 else FAIL,
        "a healthy response returns immediately",
        f"{elapsed:.2f}s, {n} attempt(s)",
    )

    print("\n" + "=" * 66)
    counts = {s: sum(1 for r in results if r[0] == s) for s in (PASS, FAIL)}
    print(f"  {counts[PASS]} passed   {counts[FAIL]} failed")
    print("=" * 66)
    for status, name, detail in results:
        if status != PASS:
            print(f"  [{status}] {name}: {detail}")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
