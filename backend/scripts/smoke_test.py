"""End-to-end smoke test for the CodeReviewer backend.

Walks every endpoint the demo touches, in the order the UI calls them, and
prints a pass/fail line for each assertion. Exits non-zero if anything failed,
so it can be wired into a script or run before a demo.

Requires a running backend:

    cd backend
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

Then, from the backend directory:

    .venv/Scripts/python.exe scripts/smoke_test.py

Use ``--base-url`` if the API is not on the default port. Add ``--no-review``
to skip the AI review section, which is the only part that spends API quota.

**``--token`` is required for the execution and review sections.** Sign-in
became mandatory in Phase 2, so ``POST /api/submissions/run`` and
``POST /api/reviews`` answer 401 to an anonymous caller - and before this flag
existed, those sections silently tested nothing but the 401. Grab the token
from the browser's devtools (Application -> Cookies -> ``__session``) or set
``SMOKE_TOKEN``. Without it the authenticated sections are skipped with a
warning rather than reported as failures.

For the parts that need no server, no token and no quota - the runner, the
comparison rules, the catalogue data - use ``scripts/check_runner.py``.

Only uses ``httpx`` (already a dependency) and the standard library, so it
needs nothing installed beyond ``requirements.txt``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"

#: Problem 1 (Contains Duplicate) is the demo problem: it has the large-input
#: performance case that turns a nested-loop solution into a 3/4 partial.
PROBLEM_ID = 1

#: Solutions are formatted with the problem's real entrypoint name, which is
#: read from the API - never hardcoded, so this file cannot drift away from
#: the starter code contract.
NAIVE_TMPL = '''\
def {fn}(nums):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] == nums[j]:
                return True
    return False
'''

OPTIMAL_TMPL = '''\
def {fn}(nums):
    seen = set()
    for n in nums:
        if n in seen:
            return True
        seen.add(n)
    return False
'''

BROKEN_TMPL = '''\
def {fn}(nums)
    return False
'''

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name} - {detail}")


def summarise() -> int:
    """Print the tally and return the process exit code."""
    print("\n" + "=" * 66)
    counts = {s: sum(1 for r in results if r[0] == s) for s in (PASS, FAIL, WARN)}
    print(f"  {counts[PASS]} passed   {counts[FAIL]} failed   {counts[WARN]} warnings")
    print("=" * 66)
    for status, name, detail in results:
        if status != PASS:
            print(f"  [{status}] {name}: {detail}")
    if counts[FAIL]:
        print("\n  A FAIL above is a real defect. A WARN on the review section is")
        print("  usually the Gemini free tier (5 requests/minute), not the code.")
    return 1 if counts[FAIL] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000", help="backend base URL"
    )
    parser.add_argument(
        "--no-review", action="store_true", help="skip the AI review section"
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SMOKE_TOKEN", ""),
        help=(
            "Clerk session token. REQUIRED for the execution and review "
            "sections - sign-in became mandatory in Phase 2, so "
            "POST /api/submissions/run and POST /api/reviews answer 401 "
            "without one. Read it from the browser's devtools "
            "(Application -> Cookies -> __session) or set SMOKE_TOKEN."
        ),
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=180.0)

    headers: dict[str, str] = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    else:
        print(
            "\n  No --token given: the execution and review sections will be\n"
            "  SKIPPED, because those endpoints require a signed-in user.\n"
        )

    print("\n=== 1. Service identity ===")
    try:
        service = client.get("/").json().get("service", "")
        record(
            PASS if "CodeReviewer" in service else FAIL,
            "GET /",
            f"service={service!r}",
        )
    except httpx.HTTPError as exc:
        record(FAIL, "GET /", f"backend unreachable at {args.base_url}: {exc}")
        print("\n  Start the backend first - see the module docstring.")
        return 1

    health = client.get("/api/health").json()
    record(
        PASS if health["status"] == "ok" else FAIL,
        "GET /api/health",
        f"llm_configured={health['llm_configured']} model={health['llm_model']}",
    )
    if not health["llm_configured"]:
        record(WARN, "LLM key", "no key configured - reviews will be rule-based")

    # Which execution backend is live, and does it work? This is the single
    # most useful line in a demo pre-flight: with the docker backend and a
    # stopped daemon, every run fails, and without this the failure surfaces
    # only when the first submission is made in front of an audience.
    backend = health.get("runner_backend")
    if backend == "docker":
        record(
            PASS if health.get("docker_ok") else FAIL,
            "execution sandbox",
            f"backend=docker image={health.get('runner_image')} "
            + ("daemon reachable" if health.get("docker_ok") else f"UNREACHABLE - {health.get('docker_error')}"),
        )
    else:
        record(
            WARN,
            "execution sandbox",
            f"backend={backend} - student code runs on this machine with no container isolation",
        )

    print("\n=== 2. Problem catalogue ===")
    problems = client.get("/api/problems").json()
    record(
        PASS if len(problems) == 5 else FAIL,
        "GET /api/problems",
        f"{len(problems)}: {', '.join(p['title'] for p in problems)}",
    )

    detail = client.get(f"/api/problems/{PROBLEM_ID}").json()
    languages = detail.get("languages") or {}
    python_spec = languages.get("python") or {}
    entrypoint = python_spec.get("entrypoint")
    starter = python_spec.get("starter")
    record(
        PASS if entrypoint and starter else FAIL,
        f"GET /api/problems/{PROBLEM_ID}",
        f"languages={sorted(languages)} entrypoint={entrypoint!r} "
        f"starter={len(starter or '')} chars",
    )

    leaked = [k for k in ("test_cases", "expected", "hidden") if k in detail]
    record(
        PASS if not leaked else FAIL,
        "no hidden test data leaked",
        "clean" if not leaked else f"leaked keys: {leaked}",
    )

    if not args.token:
        print("\n=== 3-6. Execution, review and error handling: SKIPPED ===")
        record(
            WARN,
            "authenticated sections",
            "no --token given - POST /api/submissions/run and POST /api/reviews "
            "return 401 without a Clerk session token",
        )
        return summarise()

    print("\n=== 3. Starter code contract ===")
    # Every problem, in every language it declares - not just the demo problem.
    # An `error` status here means an entrypoint name has drifted away from its
    # starter signature, which would otherwise show up as *every* submission to
    # that problem erroring.
    for problem in problems:
        pid = problem["id"]
        problem_detail = client.get(f"/api/problems/{pid}").json()
        for language, lang_spec in sorted((problem_detail.get("languages") or {}).items()):
            body = client.post(
                "/api/submissions/run",
                json={
                    "problem_id": pid,
                    "language": language,
                    "code": lang_spec.get("starter", ""),
                },
                headers=headers,
            ).json()
            status = body.get("status")
            record(
                PASS if status == "failed" else FAIL,
                f"starter {pid} {language}",
                f"status={status} (want 'failed' - 'error' means the entrypoint "
                "name no longer matches the starter signature)",
            )

    print("\n=== 4. Code execution ===")
    runs: dict[str, dict] = {}
    for label, code, want in (
        ("naive O(n^2)", NAIVE_TMPL.format(fn=entrypoint), "partial"),
        ("optimal O(n)", OPTIMAL_TMPL.format(fn=entrypoint), "passed"),
        ("syntax error", BROKEN_TMPL.format(fn=entrypoint), "error"),
    ):
        body = client.post(
            "/api/submissions/run",
            json={"problem_id": PROBLEM_ID, "language": "python", "code": code},
            headers=headers,
        ).json()
        runs[label] = body
        detail_txt = (
            f"{body.get('status')} {body.get('passed')}/{body.get('total')} "
            f"in {body.get('execution_time')}s"
        )
        if body.get("error"):
            detail_txt += f" | {body['error']['type']}: {body['error']['title']}"
        record(
            PASS if body.get("status") == want else FAIL,
            f"run {label} (want {want})",
            detail_txt,
        )

    naive_run = runs["naive O(n^2)"]
    failed = [t["name"] for t in naive_run.get("tests", []) if not t["passed"]]
    record(
        PASS if len(failed) == 1 else FAIL,
        "naive fails exactly the perf case",
        f"failed: {failed}",
    )

    optimal_run = runs["optimal O(n)"]
    record(
        PASS if optimal_run.get("passed") == optimal_run.get("total") else FAIL,
        "optimal passes everything",
        f"{optimal_run.get('passed')}/{optimal_run.get('total')}",
    )

    print("\n=== 4b. Execution detail ===")
    # Student output has to reach the client: a teaching tool where print()
    # does nothing is a teaching tool nobody can debug with.
    noisy = f"def {entrypoint}(nums):\n    print('n =', len(nums))\n    return False\n"
    noisy_run = client.post(
        "/api/submissions/run",
        json={"problem_id": PROBLEM_ID, "language": "python", "code": noisy},
        headers=headers,
    ).json()
    captured = [t.get("stdout") for t in noisy_run.get("tests", []) if t.get("stdout")]
    record(
        PASS if captured else FAIL,
        "student stdout reaches the client",
        (
            f"{len(captured)} case(s) carried output, first={captured[0]!r}"
            if captured
            else "no case returned any stdout"
        ),
    )

    per_case = [t.get("elapsed") for t in noisy_run.get("tests", [])]
    record(
        PASS if per_case and all(isinstance(v, (int, float)) and v > 0 for v in per_case) else FAIL,
        "every case reports its own elapsed time",
        f"elapsed={per_case}",
    )

    print("\n=== 4c. Language refusals ===")
    resp = client.post(
        "/api/submissions/run",
        json={"problem_id": PROBLEM_ID, "language": "cobol", "code": "x"},
        headers=headers,
    )
    record(
        PASS if resp.status_code == 400 else FAIL,
        "unknown language -> 400",
        f"HTTP {resp.status_code}: {resp.json().get('detail', '')}",
    )

    if not args.no_review:
        print("\n=== 5. AI review ===")
        reviews: dict[str, dict] = {}
        for label in ("naive O(n^2)", "optimal O(n)"):
            run = runs[label]
            payload = {
                "problem_id": PROBLEM_ID,
                "code": (NAIVE_TMPL if label.startswith("naive") else OPTIMAL_TMPL).format(
                    fn=entrypoint
                ),
                "test_result": {
                    "passed": run["passed"],
                    "total": run["total"],
                    "execution_time": run["execution_time"],
                    "status": run["status"],
                    "failed_tests": [t["name"] for t in run["tests"] if not t["passed"]],
                },
            }
            started = time.perf_counter()
            resp = client.post("/api/reviews", json=payload, headers=headers)
            elapsed = time.perf_counter() - started

            if resp.status_code != 200:
                # A 503 here is expected sometimes: the Gemini free tier allows
                # only a handful of requests per minute, and the flash models
                # intermittently answer "high demand". Neither is a code bug.
                record(
                    WARN,
                    f"review {label}",
                    f"HTTP {resp.status_code}: {resp.json().get('detail', '')}",
                )
                continue

            body = resp.json()
            reviews[label] = body
            source = body.get("source")
            record(
                PASS if source in ("gemini", "groq") else WARN,
                f"review {label}",
                f"source={source} overall={body.get('overall_score')} "
                f"eff={body.get('efficiency_score')} in {elapsed:.1f}s",
            )
            cx = body.get("complexity", {})
            record(
                PASS if cx.get("current_time") else WARN,
                f"  complexity {label}",
                f"{cx.get('current_time')} -> {cx.get('suggested_time')}",
            )
            record(
                PASS if body.get("summary") else FAIL,
                f"  summary {label}",
                (body.get("summary") or "")[:95],
            )

        if len(reviews) == 2:
            naive, optimal = reviews["naive O(n^2)"], reviews["optimal O(n)"]
            # The before/after comparison only means something if one model
            # produced both reviews. If Gemini dropped out mid-run and Groq
            # picked up the second, the score gap is partly a model change.
            sources = {naive.get("source"), optimal.get("source")}
            record(
                PASS if len(sources) == 1 else WARN,
                "both reviews came from the same model",
                f"sources={sorted(sources)}",
            )
            record(
                PASS if naive["overall_score"] < optimal["overall_score"] else FAIL,
                "naive scores below optimal",
                f"{naive['overall_score']} < {optimal['overall_score']}",
            )
            record(
                PASS if naive.get("issues") else WARN,
                "naive flags at least one issue",
                f"{len(naive.get('issues', []))} issue(s): "
                f"{[i['title'][:45] for i in naive.get('issues', [])]}",
            )
            record(
                PASS if optimal.get("hint") else WARN,
                "optimal still gets a hint",
                f"{len(optimal.get('hint', ''))} chars",
            )
    else:
        print("\n=== 5. AI review (skipped) ===")

    print("\n=== 6. Error handling ===")
    resp = client.post(
        "/api/reviews", json={"problem_id": 999, "code": "pass"}, headers=headers
    )
    record(
        PASS if resp.status_code == 404 else FAIL,
        "unknown problem id -> 404",
        f"HTTP {resp.status_code}",
    )

    resp = client.post(
        "/api/submissions/run",
        json={"problem_id": PROBLEM_ID, "code": ""},
        headers=headers,
    )
    record(
        PASS if resp.status_code in (200, 422) else FAIL,
        "empty code handled",
        f"HTTP {resp.status_code}",
    )

    return summarise()


if __name__ == "__main__":
    sys.exit(main())
