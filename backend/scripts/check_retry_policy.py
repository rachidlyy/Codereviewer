"""Offline checks for the LLM retry policy and provider chain.

These run against ``httpx.MockTransport``, so they need no API key, no network
and spend no quota - the error bodies below were captured from the live API
and are replayed verbatim.

    cd backend
    .venv/Scripts/python.exe scripts/check_retry_policy.py

Two distinctions are under test, both of which caused real bugs:

1. **503 vs 429.** Google returns 503 for transient capacity (worth retrying
   with backoff) but 429 for a spent per-minute quota (not worth retrying at
   1s). The 429 body states the real wait in ``error.details[].retryDelay``
   and sends **no** ``Retry-After`` header - reading only the header meant
   backing off 1-2s against a 50s limit and burning every attempt.
2. **Gemini vs Groq.** Gemini is primary and Groq is the fallback, so a
   Gemini failure must reach Groq rather than the student, and a Gemini
   *success* must not touch Groq at all (otherwise the model answering would
   change between calls and review scores would drift).
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

# Captured verbatim from a live Gemini 429.
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

# Captured verbatim from a live Gemini 503.
BODY_503 = {
    "error": {
        "code": 503,
        "message": "This model is currently experiencing high demand. Spikes in demand "
        "are usually temporary. Please try again later.",
        "status": "UNAVAILABLE",
    }
}

# Groq speaks the OpenAI shape, so its errors nest differently.
GROQ_BODY_429 = {
    "error": {
        "message": "Rate limit reached for model `openai/gpt-oss-120b` in organization "
        "`org_01` service tier `on_demand` on tokens per minute (TPM): Limit 8000, "
        "Used 7980, Requested 120. Please try again in 750ms.",
        "type": "tokens",
        "code": "rate_limit_exceeded",
    }
}

GEMINI_OK_BODY = {
    "candidates": [
        {"content": {"parts": [{"text": '{"overall_score": 7}'}], "role": "model"}}
    ]
}

GROQ_OK_BODY = {
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": '{"overall_score": 7}'},
            "finish_reason": "stop",
        }
    ]
}

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name} - {detail}")


def call_with(handler, target=None) -> tuple[float, bool, object, float | None, int]:
    """Run an async reviewer entry point against a mock handler.

    Returns ``(elapsed, ok, detail, retry_after, attempts)``. On success
    ``detail`` is whatever the function returned; on failure it is the error
    string. ``target`` defaults to ``_call_gemini`` so the retry-policy cases
    below are not entangled with the fallback logic.
    """
    fn = target or reviewer._call_gemini
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
        result = asyncio.run(fn("test prompt"))
        return time.perf_counter() - started, True, result, None, attempts["n"]
    except reviewer.ReviewUnavailable as exc:
        return (
            time.perf_counter() - started,
            False,
            str(exc),
            exc.retry_after,
            attempts["n"],
        )
    finally:
        reviewer.httpx.AsyncClient = original


def with_retry_delay(seconds: str) -> dict:
    """The captured 429 body, with the stated wait replaced."""
    body = {"error": dict(BODY_429["error"])}
    body["error"]["details"] = [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": seconds}
    ]
    return body


def is_groq(request: httpx.Request) -> bool:
    """Route a mock response by host, so one handler can serve both providers."""
    return "groq.com" in str(request.url)


def check_extraction() -> None:
    print("\n=== response extraction ===")

    text = reviewer._extract_gemini_text(GEMINI_OK_BODY)
    record(PASS if text == '{"overall_score": 7}' else FAIL, "reads Gemini candidates", repr(text))

    text = reviewer._extract_openai_text(GROQ_OK_BODY)
    record(PASS if text == '{"overall_score": 7}' else FAIL, "reads Groq choices", repr(text))

    # Some OpenAI-compatible gateways return HTTP 200 with an error object and
    # no ``choices`` key at all. Touching choices[0] first would raise
    # IndexError and make a provider hiccup look like a bug in our own code.
    try:
        reviewer._extract_openai_text({"error": {"message": "upstream exploded"}})
        record(FAIL, "200-with-error is detected, not IndexError", "no exception raised")
    except reviewer.ReviewUnavailable as exc:
        record(
            PASS if "upstream exploded" in str(exc) else FAIL,
            "200-with-error is detected, not IndexError",
            str(exc)[:70],
        )

    try:
        reviewer._extract_openai_text({"choices": []})
        record(FAIL, "empty choices raises a clear error", "no exception raised")
    except reviewer.ReviewUnavailable as exc:
        record(PASS, "empty choices raises a clear error", str(exc)[:70])


def check_retry_delay() -> None:
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


def check_error_messages() -> None:
    print("\n=== error message quality ===")

    described = reviewer._describe_http_error(httpx.Response(429, json=BODY_429))
    record(
        PASS if "limit: 5" in described else FAIL,
        "keeps the Gemini quota detail at the end of the message",
        f"{len(described)} chars, names the limit: {'limit: 5' in described}",
    )
    record(
        PASS if "You exceeded your current quota" in described else FAIL,
        "keeps the human-readable summary",
        described[:100] + " ...",
    )

    groq = reviewer._describe_http_error(
        httpx.Response(429, json=GROQ_BODY_429), provider="Groq"
    )
    record(
        PASS if "Groq returned HTTP 429" in groq and "Limit 8000" in groq else FAIL,
        "names the failing provider and keeps the Groq limit",
        groq[:110] + " ...",
    )
    record(
        PASS if "Gemini returned HTTP" in described else FAIL,
        "defaults to naming Gemini",
        described[:60] + " ...",
    )


def check_gemini_retry_policy() -> None:
    print("\n=== Gemini retry policy ===")

    elapsed, ok, detail, hint, n = call_with(lambda req: httpx.Response(429, json=BODY_429))
    record(
        PASS if not ok and elapsed < 2.0 and n == 1 else FAIL,
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
        return httpx.Response(200, json=GEMINI_OK_BODY)

    elapsed, ok, detail, _, n = call_with(short_wait)
    record(
        PASS if ok and n == 2 else FAIL,
        "429 stating a 2s wait is honoured and retried",
        f"{elapsed:.2f}s, {n} attempt(s), ok={ok}",
    )
    record(
        PASS if 1.8 <= elapsed <= 4.0 else FAIL,
        "the 2s wait was actually slept",
        f"{elapsed:.2f}s",
    )

    elapsed, ok, detail, _, n = call_with(lambda req: httpx.Response(503, json=BODY_503))
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

    elapsed, ok, detail, _, n = call_with(
        lambda req: httpx.Response(
            400, json={"error": {"code": 400, "message": "API key not valid"}}
        )
    )
    record(
        PASS if not ok and n == 1 and elapsed < 1.0 else FAIL,
        "400 is never retried",
        f"{n} attempt(s) in {elapsed:.2f}s",
    )
    record(
        PASS if "API key not valid" in str(detail) else FAIL,
        "400 preserves the provider message",
        str(detail)[:100],
    )

    elapsed, ok, detail, _, n = call_with(lambda req: httpx.Response(200, json=GEMINI_OK_BODY))
    record(
        PASS if ok and n == 1 else FAIL,
        "a healthy response returns immediately",
        f"{elapsed:.2f}s, {n} attempt(s)",
    )


def check_groq_retry_policy() -> None:
    print("\n=== Groq retry policy ===")

    # Unlike Gemini, Groq really does send Retry-After - so a short one must be
    # honoured rather than guessed at.
    state = {"n": 0}

    def rate_limited_once(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json=GROQ_BODY_429)
        return httpx.Response(200, json=GROQ_OK_BODY)

    elapsed, ok, detail, _, n = call_with(rate_limited_once, target=reviewer._call_groq)
    record(
        PASS if ok and n == 2 else FAIL,
        "honours Groq's Retry-After header and retries",
        f"{elapsed:.2f}s, {n} attempt(s), ok={ok}",
    )

    elapsed, ok, detail, _, n = call_with(
        lambda req: httpx.Response(400, json=GROQ_BODY_429), target=reviewer._call_groq
    )
    record(
        PASS if not ok and n == 1 else FAIL,
        "Groq 400 is never retried",
        f"{n} attempt(s)",
    )
    record(
        PASS if "Limit 8000" in str(detail) else FAIL,
        "Groq error keeps the actionable limit",
        str(detail)[:110],
    )

    elapsed, ok, detail, _, n = call_with(
        lambda req: httpx.Response(200, json=GROQ_OK_BODY), target=reviewer._call_groq
    )
    record(
        PASS if ok and str(detail) == '{"overall_score": 7}' else FAIL,
        "a healthy Groq response is extracted",
        f"{elapsed:.2f}s, {n} attempt(s)",
    )


def check_fallback_chain() -> None:
    """Gemini first, Groq only when Gemini has already failed."""
    print("\n=== provider fallback chain ===")

    saved = (config.GEMINI_API_KEY, config.GROQ_API_KEY)
    calls = {"gemini": 0, "groq": 0}

    def route(request: httpx.Request) -> httpx.Response:
        if is_groq(request):
            calls["groq"] += 1
            return httpx.Response(200, json=GROQ_OK_BODY)
        calls["gemini"] += 1
        return httpx.Response(429, json=BODY_429)

    try:
        config.GEMINI_API_KEY = "test-gemini-key"
        config.GROQ_API_KEY = "test-groq-key"

        elapsed, ok, detail, hint, n = call_with(route, target=reviewer._call_llm)
        record(
            PASS if ok and detail == ('{"overall_score": 7}', "groq") else FAIL,
            "Gemini 429 falls through to Groq",
            f"ok={ok}, detail={detail!r}",
        )
        record(
            PASS if calls["groq"] == 1 else FAIL,
            "Groq is called exactly once",
            f"gemini={calls['gemini']}, groq={calls['groq']}",
        )
        record(
            PASS if elapsed < 2.0 else FAIL,
            "the fallback does not sleep through Gemini's 50s wait",
            f"{elapsed:.2f}s total",
        )

        # A Gemini success must not touch Groq: the demo's before/after score
        # comparison is only meaningful if one model answers both reviews.
        calls["gemini"] = calls["groq"] = 0

        def gemini_ok(request: httpx.Request) -> httpx.Response:
            if is_groq(request):
                calls["groq"] += 1
                return httpx.Response(200, json=GROQ_OK_BODY)
            calls["gemini"] += 1
            return httpx.Response(200, json=GEMINI_OK_BODY)

        _, ok, detail, _, _ = call_with(gemini_ok, target=reviewer._call_llm)
        record(
            PASS if ok and detail == ('{"overall_score": 7}', "gemini") else FAIL,
            "a healthy Gemini response is labelled gemini",
            f"ok={ok}, detail={detail!r}",
        )
        record(
            PASS if calls["groq"] == 0 else FAIL,
            "Groq is never called when Gemini succeeds",
            f"groq calls={calls['groq']}",
        )

        # Both down: the student must see why, naming both providers.
        _, ok, detail, hint, _ = call_with(
            lambda req: httpx.Response(503, json=BODY_503), target=reviewer._call_llm
        )
        message = str(detail)
        record(
            PASS if not ok and "gemini:" in message and "groq:" in message else FAIL,
            "both providers failing names both in the error",
            message[:120] + " ...",
        )
        record(
            PASS if ok is False else FAIL,
            "both providers failing still raises ReviewUnavailable",
            f"ok={ok}",
        )

        # Groq alone is a valid configuration, not an error path.
        config.GEMINI_API_KEY = ""
        calls["gemini"] = calls["groq"] = 0
        _, ok, detail, _, _ = call_with(
            lambda req: httpx.Response(200, json=GROQ_OK_BODY), target=reviewer._call_llm
        )
        record(
            PASS if ok and detail == ('{"overall_score": 7}', "groq") else FAIL,
            "Groq-only configuration works without a Gemini key",
            f"ok={ok}, detail={detail!r}",
        )
        record(
            PASS if calls["gemini"] == 0 else FAIL,
            "Gemini is skipped entirely when unconfigured",
            f"gemini calls={calls['gemini']}",
        )

        # Neither configured - the message must be explicit, not a mystery 503.
        config.GROQ_API_KEY = ""
        _, ok, detail, _, _ = call_with(
            lambda req: httpx.Response(200, json=GEMINI_OK_BODY), target=reviewer._call_llm
        )
        message = str(detail)
        record(
            PASS if not ok and message.count("no API key configured") == 2 else FAIL,
            "no keys configured says so for both providers",
            message[:120] + " ...",
        )
    finally:
        config.GEMINI_API_KEY, config.GROQ_API_KEY = saved


def check_config_description() -> None:
    print("\n=== configuration reporting ===")

    saved = (config.GEMINI_API_KEY, config.GROQ_API_KEY)
    try:
        config.GEMINI_API_KEY = "k"
        config.GROQ_API_KEY = "k"
        described = config.llm_model() or ""
        record(
            PASS if "fallback:" in described and described.count("->") == 1 else FAIL,
            "llm_model() shows the chain in order",
            described,
        )

        config.GROQ_API_KEY = ""
        described = config.llm_model() or ""
        record(
            PASS if "fallback:" not in described and described else FAIL,
            "llm_model() omits the fallback when unset",
            described,
        )

        config.GEMINI_API_KEY = ""
        record(
            PASS if config.llm_model() is None and not config.llm_enabled() else FAIL,
            "no keys means offline mode",
            f"llm_model={config.llm_model()!r}, enabled={config.llm_enabled()}",
        )
    finally:
        config.GEMINI_API_KEY, config.GROQ_API_KEY = saved


def main() -> int:
    check_extraction()
    check_retry_delay()
    check_error_messages()
    check_gemini_retry_policy()
    check_groq_retry_policy()
    check_fallback_chain()
    check_config_description()

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
