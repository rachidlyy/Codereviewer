"""Child-process harness that executes one test case against student code.

This module is **never imported** by the API. It is launched as a separate
``python`` process by :mod:`app.services.code_runner`, one process per test
case, so that:

* a slow or infinite loop in the student's code can be killed by the parent
  via a hard timeout;
* a crash or ``sys.exit`` in student code cannot take down the API server;
* student code can never see the API process' environment or memory.

Protocol
--------
stdin  : JSON ``{"code": str, "call": str, "expected": str}``
stdout : a single line beginning with the ``RESULT_SENTINEL`` marker,
         followed by the JSON result object.

Anything the student prints is captured and returned under ``stdout``
instead of being written to the real stdout, so it cannot corrupt the
result line.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any

RESULT_SENTINEL = "__CODERUNNER_RESULT__"

#: Keep captured student output bounded so a runaway print loop cannot
#: exhaust memory or bloat the API response.
MAX_CAPTURED_CHARS = 4000


def _values_match(actual: Any, expected: Any) -> bool:
    """Compare student output to the expected value, a little forgivingly.

    Exact equality is tried first. Beyond that we tolerate two common
    sources of spurious failure in an educational setting:

    * returning ``(0, 1)`` where ``[0, 1]`` was expected (and vice versa);
    * returning ``4.0`` where ``4`` was expected.
    """
    if actual == expected:
        return True

    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            return False
        return all(_values_match(a, b) for a, b in zip(actual, expected))

    # bool is a subclass of int, but `True == 1` already matched above, so
    # this branch only ever sees genuine numeric comparisons.
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)

    return False


def _failure(error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"passed": False, "error_type": error_type, "message": message, **extra}


def _evaluate(code: str, call: str, expected_expr: str) -> dict[str, Any]:
    """Compile, execute and check the submission. Returns the result dict."""
    try:
        compiled = compile(code, "main.py", "exec")
    except SyntaxError as exc:
        line = exc.lineno or 0
        detail = exc.msg or "invalid syntax"
        return _failure(
            "syntax",
            f"Syntax error on line {line}: {detail}",
            line=line,
        )
    except ValueError as exc:
        # e.g. source containing null bytes
        return _failure("syntax", f"Your code could not be parsed: {exc}")

    namespace: dict[str, Any] = {"__name__": "__student__"}
    try:
        exec(compiled, namespace)  # noqa: S102 - executing student code is the point
    except BaseException as exc:  # noqa: BLE001 - student code may raise anything
        return _failure("runtime", f"{type(exc).__name__}: {exc}")

    try:
        actual = eval(call, namespace)  # noqa: S307 - call expression is authored by us
    except SyntaxError as exc:
        line = exc.lineno or 0
        return _failure("syntax", f"Syntax error on line {line}: {exc.msg}", line=line)
    except BaseException as exc:  # noqa: BLE001
        return _failure("runtime", f"{type(exc).__name__}: {exc}")

    try:
        expected = eval(expected_expr, {"__builtins__": {}})  # noqa: S307
    except BaseException as exc:  # noqa: BLE001 - malformed test case
        return _failure("runtime", f"Could not evaluate expected value: {exc}")

    passed = _values_match(actual, expected)
    return {
        "passed": passed,
        "error_type": None,
        "message": None,
        "actual": repr(actual),
        "expected": repr(expected),
    }


def main() -> None:
    real_stdout = sys.stdout

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        real_stdout.write(
            RESULT_SENTINEL
            + json.dumps(_failure("runtime", f"Runner could not read the request: {exc}"))
            + "\n"
        )
        return

    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            result = _evaluate(
                payload.get("code", ""),
                payload.get("call", ""),
                payload.get("expected", "None"),
            )
    except BaseException as exc:  # noqa: BLE001 - last-resort guard
        result = _failure("runtime", f"{type(exc).__name__}: {exc}")

    output = captured.getvalue()
    if output:
        if len(output) > MAX_CAPTURED_CHARS:
            output = output[:MAX_CAPTURED_CHARS] + "\n... (output truncated)"
        result["stdout"] = output

    real_stdout.write(RESULT_SENTINEL + json.dumps(result) + "\n")
    real_stdout.flush()


if __name__ == "__main__":
    main()
