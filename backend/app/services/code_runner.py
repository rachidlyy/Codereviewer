"""Python code execution against predefined test cases.

Each test case runs in its own isolated child process (see
``_runner_harness.py``) with a hard timeout, so a slow or crashing
submission can never affect the API server.

This module is deliberately self-contained: it is the single place that
knows how code gets executed. Swapping the local subprocess runner for a
Docker sandbox later means reimplementing ``run_submission`` here and
nothing else (see plan section 9).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app import config
from app.data.problems import Problem
from app.data.test_cases import TestCase, get_test_cases
from app.services._runner_harness import RESULT_SENTINEL

HARNESS_PATH = Path(__file__).resolve().parent / "_runner_harness.py"

SUPPORTED_LANGUAGES = {"python", "python3", "py"}

#: Friendly, student-facing error copy (plan section 16).
_ERROR_COPY: dict[str, tuple[str, str]] = {
    "syntax": (
        "Syntax Error",
        "Your code could not be executed.",
    ),
    "runtime": (
        "Runtime Error",
        "The program raised an exception while running.",
    ),
    "timeout": (
        "Execution Timed Out",
        "Your program exceeded the allowed execution time.",
    ),
}


def _python_executable() -> str:
    """Interpreter used for student code.

    Defaults to the interpreter running the API server so the venv is
    reused without any extra configuration.
    """
    return config.PYTHON_EXECUTABLE or sys.executable


def _child_env() -> dict[str, str]:
    """Minimal environment for the child process.

    Student code must not be able to read the API process' secrets - most
    importantly ``GEMINI_API_KEY`` - so we pass an explicit allow-list
    rather than inheriting ``os.environ``.
    """
    allow = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "LANG", "HOME")
    env = {key: os.environ[key] for key in allow if key in os.environ}
    env.setdefault("PATH", "")
    return env


def check_syntax(code: str) -> dict[str, Any] | None:
    """Compile-only check so a syntax error fails fast and once.

    ``compile`` parses without executing, so this is safe to run in-process.
    Returns an error dict, or None when the code parses cleanly.
    """
    try:
        compile(code, "main.py", "exec")
    except SyntaxError as exc:
        line = exc.lineno or 0
        return {
            "type": "syntax",
            "title": _ERROR_COPY["syntax"][0],
            "message": _ERROR_COPY["syntax"][1],
            "line": line,
            "detail": f"Line {line}: {exc.msg}" if line else (exc.msg or "invalid syntax"),
        }
    except ValueError as exc:
        return {
            "type": "syntax",
            "title": _ERROR_COPY["syntax"][0],
            "message": _ERROR_COPY["syntax"][1],
            "line": None,
            "detail": str(exc),
        }
    return None


def _build_error(error_type: str, detail: str, line: int | None = None) -> dict[str, Any]:
    title, message = _ERROR_COPY.get(error_type, ("Execution Error", "Something went wrong."))
    payload: dict[str, Any] = {
        "type": error_type,
        "title": title,
        "message": message,
        "line": line,
        "detail": detail,
    }
    return payload


def _run_case(
    code: str,
    test_case: TestCase,
    entrypoint: str,
    timeout: float,
) -> tuple[dict[str, Any], float]:
    """Execute a single test case. Returns (result, elapsed_seconds)."""
    call = f"{entrypoint}({test_case['input']})"
    payload = json.dumps(
        {
            "code": code,
            "call": call,
            "expected": test_case["expected"],
        }
    )

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="codementor-run-") as workdir:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [_python_executable(), "-I", str(HARNESS_PATH)],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=workdir,
                env=_child_env(),
                check=False,
            )
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - started
        return (
            {
                "passed": False,
                "error_type": "timeout",
                "message": f"Exceeded the {timeout:g}s time limit for this test case.",
            },
            elapsed,
        )
    except OSError as exc:
        elapsed = time.perf_counter() - started
        return (
            {
                "passed": False,
                "error_type": "runtime",
                "message": f"Could not start the Python interpreter: {exc}",
            },
            elapsed,
        )

    elapsed = time.perf_counter() - started
    parsed = _parse_harness_output(completed.stdout)
    if parsed is None:
        detail = (completed.stderr or completed.stdout or "no output").strip()
        return (
            {
                "passed": False,
                "error_type": "runtime",
                "message": f"The runner produced no result. {detail[:300]}",
            },
            elapsed,
        )
    return parsed, elapsed


def _parse_harness_output(stdout: str) -> dict[str, Any] | None:
    """Extract the sentinel-prefixed JSON line from the harness stdout."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_SENTINEL):
            try:
                return json.loads(line[len(RESULT_SENTINEL) :])
            except json.JSONDecodeError:
                return None
    return None


def _determine_status(results: list[dict[str, Any]]) -> str:
    """Map per-case outcomes onto the plan's status vocabulary.

    ``passed`` | ``partial`` | ``failed`` | ``error`` | ``timeout``
    """
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    if total and passed == total:
        return "passed"
    if passed:
        return "partial"
    if total and all(r.get("error_type") == "timeout" for r in results):
        return "timeout"
    if any(r.get("error_type") in {"syntax", "runtime"} for r in results):
        return "error"
    return "failed"


def _summarise_error(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most useful error to surface to the student."""
    for error_type in ("syntax", "runtime", "timeout"):
        for result in results:
            if result.get("error_type") == error_type:
                return _build_error(
                    error_type,
                    result.get("message") or "",
                    result.get("line"),
                )
    return None


def _empty_result(total: int) -> dict[str, Any]:
    return {
        "status": "error",
        "passed": 0,
        "total": total,
        "execution_time": 0.0,
        "tests": [],
        "error": None,
    }


def run_submission(problem: Problem, code: str) -> dict[str, Any]:
    """Run a submission against every test case for the problem.

    Returns a dict matching the ``POST /api/submissions/run`` response
    contract (plan section 15), with an extra ``error`` object so the UI
    can render the friendly messages from plan section 16.
    """
    cases = get_test_cases(problem["id"])
    if not cases:
        result = _empty_result(0)
        result["error"] = _build_error("runtime", "No test cases are configured for this problem.")
        return result

    entrypoint = problem["entrypoint"]
    default_timeout = config.TEST_TIMEOUT_SECONDS

    # Fail fast on a syntax error: every case would fail identically.
    syntax_error = check_syntax(code)
    if syntax_error is not None:
        result = _empty_result(len(cases))
        result["tests"] = [
            {
                "index": index + 1,
                "name": case.get("name") or f"Test {index + 1}",
                "passed": False,
                "error_type": "syntax",
                "message": syntax_error["detail"],
                "actual": None,
                "expected": case["expected"],
            }
            for index, case in enumerate(cases)
        ]
        result["error"] = syntax_error
        return result

    tests: list[dict[str, Any]] = []
    total_elapsed = 0.0
    deadline = time.perf_counter() + config.SUBMISSION_TIMEOUT_SECONDS

    for index, case in enumerate(cases):
        name = case.get("name") or f"Test {index + 1}"

        if time.perf_counter() > deadline:
            tests.append(
                {
                    "index": index + 1,
                    "name": name,
                    "passed": False,
                    "error_type": "timeout",
                    "message": "Submission exceeded the total time budget.",
                    "actual": None,
                    "expected": case["expected"],
                }
            )
            continue

        timeout = float(case.get("timeout", default_timeout))
        outcome, elapsed = _run_case(code, case, entrypoint, timeout)
        total_elapsed += elapsed

        tests.append(
            {
                "index": index + 1,
                "name": name,
                "passed": bool(outcome.get("passed")),
                "error_type": outcome.get("error_type"),
                "message": outcome.get("message"),
                "actual": outcome.get("actual"),
                "expected": outcome.get("expected", case["expected"]),
            }
        )

    return {
        "status": _determine_status(tests),
        "passed": sum(1 for test in tests if test["passed"]),
        "total": len(tests),
        "execution_time": round(total_elapsed, 3),
        "tests": tests,
        "error": _summarise_error(tests),
    }
