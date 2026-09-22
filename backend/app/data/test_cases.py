"""Structured test cases, loaded from ``test_cases.json``.

Format
------
A JSON object keyed by ``problem_id`` - as a **string**, because JSON has no
integer keys - each value a list of cases::

    {
      "1": [
        {"name": "Basic duplicate", "args": [[1, 2, 3, 1]], "expected": true}
      ]
    }

``args``
    The positional arguments of the call, as JSON. ``args: [[1, 2, 3, 1]]``
    is executed as ``entrypoint([1, 2, 3, 1])``.

    JSON rather than a language-specific expression is the entire point: the
    same case has to be runnable from Python, JavaScript, Java and C++. The
    previous format used Python expressions (``"[1, 2, 3, 1]"``,
    ``"list(range(20000))"``), which could never generalise past Python.

``expected``
    The expected return value, as JSON. Compared by the **runner**, not by
    the language harness - see ``services/code_runner.py``. Keeping the
    comparison in one place is what stops four languages needing four
    implementations of the same tolerance rules.

``generate``
    An alternative to ``args`` for inputs too large to write as a literal.
    It expands to the args array:

    ``{"kind": "range", "n": 200000}``  ->  ``[list(range(200000))]``

    i.e. one positional argument holding the integers 0..n-1. This replaces
    the old Python-only ``list(range(200000))`` and is why the large-input
    performance case survives in every language.

``timeout``
    Per-case override, in seconds. Used by the large-input case so an
    inefficient solution is reported as a timeout rather than hanging the
    request.

``name``
    Short human label shown in the results UI.

``comparator``
    Optional. ``exact`` (default) or ``unordered``, for answers where element
    order is not part of the contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"


class TestCase(TypedDict, total=False):
    name: str
    args: list[Any]
    generate: dict[str, Any]
    expected: Any
    timeout: float
    comparator: str


def _load() -> dict[int, list[TestCase]]:
    """Read the catalogue, converting the JSON string keys back to ints."""
    with TEST_CASES_PATH.open(encoding="utf-8") as handle:
        raw: dict[str, list[TestCase]] = json.load(handle)
    return {int(problem_id): cases for problem_id, cases in raw.items()}


TEST_CASES: dict[int, list[TestCase]] = _load()


def get_test_cases(problem_id: int) -> list[TestCase]:
    """Return the test cases for a problem (empty list when unknown)."""
    return TEST_CASES.get(problem_id, [])


class BadCase(ValueError):
    """A test case that cannot be turned into arguments."""


def resolve_args(case: TestCase) -> list[Any]:
    """Expand a case into its positional arguments.

    ``args`` is used directly; ``generate`` is expanded. Raises
    :class:`BadCase` when neither is usable, which the runner reports as a
    failure for that case rather than letting it take down the request.
    """
    if "args" in case:
        return case["args"]

    spec = case.get("generate")
    if not spec:
        raise BadCase("The test case declares neither 'args' nor 'generate'.")

    kind = spec.get("kind")
    if kind == "range":
        try:
            n = int(spec.get("n", 0))
        except (TypeError, ValueError) as exc:
            raise BadCase(f"'generate.range' needs an integer 'n', got {spec.get('n')!r}.") from exc
        if n < 0:
            raise BadCase(f"'generate.range' needs a non-negative 'n', got {n}.")
        return [list(range(n))]

    raise BadCase(f"Unknown generate kind {kind!r}.")


def validate_test_cases() -> list[str]:
    """Structural checks over the whole catalogue.

    Returns a list of human-readable problems, empty when the file is sound.
    Deliberately *not* run at import: a broken data file should be reported
    by the smoke test and by pytest, not crash the API at startup - a dead
    server also takes down ``/docs`` and ``/api/health``, which are the tools
    you would use to see what is wrong.
    """
    problems: list[str] = []

    for problem_id, cases in sorted(TEST_CASES.items()):
        if not cases:
            problems.append(f"problem {problem_id}: no test cases")
            continue

        for index, case in enumerate(cases, start=1):
            where = f"problem {problem_id} case {index} ({case.get('name') or 'unnamed'})"
            if "expected" not in case:
                problems.append(f"{where}: no 'expected' value")
            has_args, has_generate = "args" in case, "generate" in case
            if has_args and has_generate:
                problems.append(f"{where}: declares both 'args' and 'generate'")
            elif not has_args and not has_generate:
                problems.append(f"{where}: declares neither 'args' nor 'generate'")
            if has_generate:
                try:
                    resolve_args(case)
                except BadCase as exc:
                    problems.append(f"{where}: {exc}")
            if case.get("comparator") not in (None, "exact", "unordered"):
                problems.append(f"{where}: unknown comparator {case['comparator']!r}")

    return problems
