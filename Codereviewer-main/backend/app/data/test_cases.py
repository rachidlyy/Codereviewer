"""Structured test cases for the MVP problem set.

Format (see plan section 10) - a dict keyed by `problem_id`, each value a
list of cases::

    TEST_CASES = {
        1: [
            {"input": "[1, 2, 3, 1]", "expected": "True"},
        ]
    }

Two small extensions are used by the runner:

* ``name``    - a short human label shown in the results UI.
* ``timeout`` - per-case override, in seconds. Used by the large-input
  case so an inefficient solution is reported as a timeout rather than
  hanging the request.

``input`` is the argument list of the call, so a case with ``input`` of
``"[2, 7, 11, 15], 9"`` is executed as ``twoSum([2, 7, 11, 15], 9)``.
``expected`` is a Python expression compared against the returned value.
"""

from __future__ import annotations

from typing import TypedDict


class TestCase(TypedDict, total=False):
    input: str
    expected: str
    name: str
    timeout: float


TEST_CASES: dict[int, list[TestCase]] = {
    # --- 1. Contains Duplicate ------------------------------------------
    1: [
        {
            "name": "Basic duplicate",
            "input": "[1, 2, 3, 1]",
            "expected": "True",
        },
        {
            "name": "All distinct",
            "input": "[1, 2, 3, 4]",
            "expected": "False",
        },
        {
            "name": "Empty array",
            "input": "[]",
            "expected": "False",
        },
        {
            # 20,000 distinct values. A hash-set solution answers this
            # instantly; a nested-loop solution performs ~200M comparisons
            # and exceeds the timeout. This is the case that turns the
            # demo's O(n^2) submission into "3/4 tests passed" and gives
            # the AI reviewer something real to talk about.
            "name": "Large input (performance)",
            "input": "list(range(20000))",
            "expected": "False",
            "timeout": 3.0,
        },
    ],
    # --- 2. Two Sum ------------------------------------------------------
    2: [
        {
            "name": "Basic pair",
            "input": "[2, 7, 11, 15], 9",
            "expected": "[0, 1]",
        },
        {
            "name": "Middle pair",
            "input": "[3, 2, 4], 6",
            "expected": "[1, 2]",
        },
        {
            "name": "Repeated values",
            "input": "[3, 3], 6",
            "expected": "[0, 1]",
        },
    ],
    # --- 3. Valid Anagram ------------------------------------------------
    3: [
        {
            "name": "Valid anagram",
            "input": '"anagram", "nagaram"',
            "expected": "True",
        },
        {
            "name": "Not an anagram",
            "input": '"rat", "car"',
            "expected": "False",
        },
        {
            "name": "Both empty",
            "input": '"", ""',
            "expected": "True",
        },
    ],
    # --- 4. Binary Search ------------------------------------------------
    4: [
        {
            "name": "Target present",
            "input": "[-1, 0, 3, 5, 9, 12], 9",
            "expected": "4",
        },
        {
            "name": "Target absent",
            "input": "[-1, 0, 3, 5, 9, 12], 2",
            "expected": "-1",
        },
        {
            "name": "Single element",
            "input": "[5], 5",
            "expected": "0",
        },
    ],
    # --- 5. Maximum Subarray ---------------------------------------------
    5: [
        {
            "name": "Mixed signs",
            "input": "[-2, 1, -3, 4, -1, 2, 1, -5, 4]",
            "expected": "6",
        },
        {
            "name": "Single element",
            "input": "[1]",
            "expected": "1",
        },
        {
            "name": "All positive",
            "input": "[5, 4, -1, 7, 8]",
            "expected": "23",
        },
    ],
}


def get_test_cases(problem_id: int) -> list[TestCase]:
    """Return the test cases for a problem (empty list when unknown)."""
    return TEST_CASES.get(problem_id, [])
