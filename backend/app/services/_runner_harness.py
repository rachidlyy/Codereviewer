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
stdin::

    {"code": str, "entrypoint": str, "args": [<json values>]}

stdout: a single line beginning with ``RESULT_SENTINEL`` followed by JSON::

    {"ok": true,  "serialisable": true,  "actual": <json>, "actual_repr": "...",
     "compute": 0.0012}
    {"ok": true,  "serialisable": false, "actual_repr": "...", "compute": 0.0012}
    {"ok": false, "error_type": "syntax" | "runtime", "message": "...", "line": n}

``compute`` is seconds spent inside the student's own code, measured from
executing the module to getting the answer. It deliberately excludes
interpreter startup: on Windows that costs ~0.9s, which is roughly a thousand
times what a typical solution actually does, so including it would make the
reported time meaningless and would defeat the input-scaling measurements the
complexity analysis depends on.

**This harness does not compare anything.** ``expected`` is never sent to it,
for two reasons: student code cannot read the answer out of its own process,
and the comparison rules live in exactly one place (``code_runner``) instead
of once per language. The harness answers only "what did this return, and how
long did the student's own code take?".

The arguments arrive already resolved - ``generate`` specs are expanded by the
parent - so every harness in every language receives the same concrete values.
Anything the student prints is captured and returned under ``stdout`` instead
of being written to the real stdout, so it cannot corrupt the result line.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from typing import Any

RESULT_SENTINEL = "__CODERUNNER_RESULT__"

#: Keep captured student output bounded so a runaway print loop cannot
#: exhaust memory or bloat the API response.
MAX_CAPTURED_CHARS = 4000

#: The same bound applies to a returned value's repr. A student can return a
#: 10-million-element list; the response must not grow to match.
MAX_REPR_CHARS = 2000

#: Appended when something was cut, so the student is told their output is
#: incomplete rather than shown a silently shortened version of it.
#:
#: Named rather than inlined because ``docker/runner-node/harness.js`` has the
#: same constant and the two must stay byte-identical - a student printing
#: 10,000 lines should get the same answer in either language. ``check_runner``
#: section 11 compares them directly.
TRUNCATION_MARKER = " ... (truncated)"


def _failure(error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error_type": error_type, "message": message, **extra}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + TRUNCATION_MARKER


def _evaluate(code: str, entrypoint: str, args: list[Any]) -> dict[str, Any]:
    """Compile, execute and call the entrypoint. Returns the result dict."""
    try:
        compiled = compile(code, "main.py", "exec")
    except SyntaxError as exc:
        line = exc.lineno or 0
        detail = exc.msg or "invalid syntax"
        return _failure("syntax", f"Syntax error on line {line}: {detail}", line=line)
    except ValueError as exc:
        # e.g. source containing null bytes
        return _failure("syntax", f"Your code could not be parsed: {exc}")

    namespace: dict[str, Any] = {"__name__": "__student__"}

    # Time the student's own code, from executing the module to getting the
    # answer. This deliberately excludes interpreter startup, which on Windows
    # costs ~0.9s - roughly a thousand times the work a typical solution does.
    # Reporting that as "execution time" would be a lie, and comparing two
    # input sizes to infer complexity (plan phase 5) would measure startup
    # noise instead of the algorithm.
    started = time.perf_counter()

    try:
        exec(compiled, namespace)  # noqa: S102 - executing student code is the point
    except BaseException as exc:  # noqa: BLE001 - student code may raise anything
        return _failure("runtime", f"{type(exc).__name__}: {exc}")

    # Look the function up rather than eval'ing a call expression. A missing or
    # misspelled entrypoint then produces a message that names the problem,
    # instead of a bare NameError the student has to decode.
    function = namespace.get(entrypoint)
    if function is None:
        return _failure(
            "runtime",
            f"Your code does not define anything called '{entrypoint}'. "
            "Keep the function name from the starter code.",
        )
    if not callable(function):
        return _failure(
            "runtime",
            f"'{entrypoint}' is defined but is not a function.",
        )

    try:
        actual = function(*args)
    except BaseException as exc:  # noqa: BLE001
        return _failure("runtime", f"{type(exc).__name__}: {exc}")

    return _success(actual, time.perf_counter() - started)


def _success(actual: Any, compute_seconds: float) -> dict[str, Any]:
    """Package a return value for the parent, which does the comparing.

    A JSON-serialisable value travels as JSON so the parent can compare it
    structurally. Anything else (a set, a custom object) travels as its repr,
    which the parent recovers with ``ast.literal_eval`` where possible.
    """
    try:
        # Round-trip rather than only dumps: this is what the parent will
        # actually receive, so a value that cannot survive it is caught here.
        encoded = json.loads(json.dumps(actual))
    except (TypeError, ValueError, RecursionError):
        return {
            "ok": True,
            "serialisable": False,
            "actual_repr": _truncate(repr(actual), MAX_REPR_CHARS),
            "compute": compute_seconds,
        }

    return {
        "ok": True,
        "serialisable": True,
        "actual": encoded,
        "actual_repr": _truncate(repr(actual), MAX_REPR_CHARS),
        "compute": compute_seconds,
    }


class _CappedBuffer(io.TextIOBase):
    """A stdout replacement that stops storing once it is full.

    ``io.StringIO`` accumulates every byte a runaway ``print`` loop produces,
    so a submission printing ten million lines would exhaust the container's
    memory ceiling and be reported as an out-of-memory failure. That verdict
    is technically true and completely useless - the student's actual mistake
    was printing too much, and the report should say so.

    Capping on write keeps memory flat no matter how much is printed, and lets
    the result carry an honest "truncated" marker instead.

    ``truncated`` is set only when a write was actually cut short, not merely
    when the buffer is full. The first version tested ``size >= limit`` after
    every write, so output landing on exactly 4,000 characters was labelled
    truncated although nothing had been lost. ``docker/runner-node/harness.js``
    keeps the same semantics, and ``check_runner.py`` section 11 asserts the two
    caps agree.
    """

    encoding = "utf-8"

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: list[str] = []
        self._size = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self._size < self._limit:
            room = self._limit - self._size
            if len(text) > room:
                self.truncated = True
            self._chunks.append(text[:room])
            self._size += min(len(text), room)
        elif text:
            self.truncated = True
        # Report the full length, as a real stream would: callers such as
        # print() rely on the return value to know the write succeeded.
        return len(text)

    def flush(self) -> None:
        return None

    def value(self) -> str:
        text = "".join(self._chunks)
        if self.truncated:
            return text + TRUNCATION_MARKER
        return text


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

    captured = _CappedBuffer(MAX_CAPTURED_CHARS)
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            result = _evaluate(
                payload.get("code", ""),
                payload.get("entrypoint", ""),
                payload.get("args") or [],
            )
    except BaseException as exc:  # noqa: BLE001 - last-resort guard
        result = _failure("runtime", f"{type(exc).__name__}: {exc}")

    output = captured.value()
    if output:
        result["stdout"] = output
        # Told separately from the truncation marker so the UI can explain
        # *why* the output stops, rather than just showing an ellipsis.
        result["stdout_truncated"] = captured.truncated

    real_stdout.write(RESULT_SENTINEL + json.dumps(result) + "\n")
    real_stdout.flush()


if __name__ == "__main__":
    main()
