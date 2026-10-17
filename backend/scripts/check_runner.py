"""Offline checks for the code runner and the catalogue data.

No server, no auth token, no API quota, no Docker. Imports the real modules
and exercises them directly, which makes it the fastest way to answer "did I
just break the runner?".

    cd backend
    .venv/Scripts/python.exe scripts/check_runner.py

It complements ``smoke_test.py``: that one proves the HTTP surface works
end to end but needs a running server and a Clerk token, this one proves the
execution and comparison logic is correct and needs neither.

The headline assertion is the demo's: problem 1 with a nested-loop solution
must produce exactly ``3/4``, failing only the large-input performance case.
If a refactor changes that number, the demo stops telling its story - so it is
asserted here rather than noticed during a presentation.
"""

from __future__ import annotations

import importlib.util
import math
import re
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

# Make `app` importable when run as `python scripts/check_runner.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.data import problems as problem_data  # noqa: E402
from app.data import scaling  # noqa: E402
from app.data import test_cases as test_case_data  # noqa: E402
from app.deps import current_user  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.saved_code import SavedCode  # noqa: E402
from app.models.submission import Submission  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routes.saved_code import get_saved_code, put_saved_code  # noqa: E402
from app.schemas.saved_code import SavedCodeIn, SavedCodeOut  # noqa: E402
from app.schemas.submission import RunResponse  # noqa: E402
from app.services import code_runner  # noqa: E402
from app.services.code_runner import (  # noqa: E402
    UnsupportedLanguage,
    _compare,
    _values_match,
    resolve_language,
    run_submission,
)
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import func as sa_func  # noqa: E402
from sqlalchemy import select as sa_select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"  [{status}] {name} - {detail}")


def check(condition: bool, name: str, detail: str) -> None:
    record(PASS if condition else FAIL, name, detail)


def _load_module(path: Path):
    """Import a standalone script by path.

    The container-side entrypoint and the child harness are both deliberately
    *not* part of the ``app`` package - one runs inside the sandbox, the other
    runs as a throwaway child process - so neither can be imported normally.
    Loading them by path is what lets section 11 compare their sentinels
    against the API's copies rather than grepping for them.
    """
    spec = importlib.util.spec_from_file_location(f"_probe_{path.stem}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: `const NAME = <literal>;` on its own line, where the literal is a plain
#: string or a plain integer. Deliberately narrow - see `_js_constants`.
_JS_CONSTANT = re.compile(r"^const\s+([A-Z][A-Z0-9_]*)\s*=\s*(.+?);\s*$", re.MULTILINE)


def _js_constants(path: Path) -> dict[str, str]:
    """Read a few ``const`` literals out of a JavaScript source file.

    Python cannot import a JavaScript module, so the JavaScript half of section
    11 has to be read as text where the Python half is compared as real
    attributes. That is a genuinely weaker check, so the pattern is
    deliberately restricted to exact string and integer literals - the one
    shape a regex cannot be fooled by - and anything else is simply absent from
    the result rather than guessed at. The calls in section 11 treat a missing
    key as a failure, not as a pass.

    The end-to-end evidence that the JavaScript harness is wired up is section
    2, which runs twelve JavaScript submissions through the real sandbox.
    """
    found: dict[str, str] = {}
    for match in _JS_CONSTANT.finditer(path.read_text(encoding="utf-8")):
        name, raw = match.group(1), match.group(2).strip()
        if len(raw) >= 2 and raw[0] in "'\"`" and raw[-1] == raw[0]:
            found[name] = raw[1:-1]
        elif raw.isdigit():
            found[name] = raw
    return found


def _tagged(image: str) -> str:
    """``name`` -> ``name:latest``, leaving an already-tagged ref alone.

    Not cosmetic. This Docker build (29.7.2) resolves a bare image name for
    ``docker run`` but **not** for ``docker image inspect``, which answers
    ``Error response from daemon: No such image: codereviewer-runner-python``.
    Since the whole staleness check rests on reading an image's build time, the
    tag has to be spelled out here even though the runner itself can omit it.

    The tag lives in the last path segment, so a registry host that carries a
    port - ``localhost:5000/foo`` - is not mistaken for a tagged reference.
    """
    if "@" in image:
        return image
    return image if ":" in image.rsplit("/", 1)[-1] else f"{image}:latest"


def _image_created_at(image: str) -> datetime | None:
    """A sandbox image's build time, as an aware UTC datetime.

    Docker prints nanosecond precision (``2026-09-22T05:41:50.27237144Z``) and
    ``datetime.fromisoformat`` only accepts microseconds, so the fraction is
    trimmed rather than parsed - the sub-second digits do not matter here.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [config.DOCKER_BINARY, "image", "inspect", _tagged(image), "--format", "{{.Created}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    raw = (completed.stdout or "").strip()
    if completed.returncode != 0 or not raw:
        return None

    text = raw.replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        # Only the *leading* run of digits is the fraction - the UTC offset
        # that follows it is also made of digits ("+00:00"), so a naive
        # "strip every digit" would eat the offset and shift the timestamp.
        index = 0
        while index < len(tail) and tail[index].isdigit():
            index += 1
        text = f"{head}.{tail[: min(index, 6)]}{tail[index:]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Reference solutions. These are the ground truth: if one of them does not
# pass, the runner or the test data is wrong, not the solution.
#
# Written with a dedent helper rather than escaped "\n" strings, because these
# are the specification the test data is checked against and they have to be
# readable enough to verify by eye. Two languages' worth of solutions is 24 of
# them, and an unreadable ground truth is a useless one.
# --------------------------------------------------------------------------


def _code(text: str) -> str:
    return textwrap.dedent(text).strip() + "\n"


REFERENCE: dict[int, str] = {
    1: _code(
        """
        def containsDuplicate(nums):
            return len(nums) != len(set(nums))
        """
    ),
    2: _code(
        """
        def twoSum(nums, target):
            seen = {}
            for i, n in enumerate(nums):
                if target - n in seen:
                    return [seen[target - n], i]
                seen[n] = i
            return []
        """
    ),
    3: _code(
        """
        def isAnagram(s, t):
            return sorted(s) == sorted(t)
        """
    ),
    4: _code(
        """
        def search(nums, target):
            low, high = 0, len(nums) - 1
            while low <= high:
                mid = (low + high) // 2
                if nums[mid] == target:
                    return mid
                if nums[mid] < target:
                    low = mid + 1
                else:
                    high = mid - 1
            return -1
        """
    ),
    5: _code(
        """
        def maxSubArray(nums):
            best = current = nums[0]
            for n in nums[1:]:
                current = max(n, current + n)
                best = max(best, current)
            return best
        """
    ),
    6: _code(
        """
        def isValid(s):
            pairs = {")": "(", "]": "[", "}": "{"}
            stack = []
            for ch in s:
                if ch in "([{":
                    stack.append(ch)
                elif not stack or stack.pop() != pairs[ch]:
                    return False
            return not stack
        """
    ),
    7: _code(
        """
        def groupAnagrams(strs):
            groups = {}
            for word in strs:
                groups.setdefault("".join(sorted(word)), []).append(word)
            return [sorted(group) for group in groups.values()]
        """
    ),
    8: _code(
        """
        def productExceptSelf(nums):
            n = len(nums)
            out = [1] * n
            left = 1
            for i in range(n):
                out[i] = left
                left *= nums[i]
            right = 1
            for i in range(n - 1, -1, -1):
                out[i] *= right
                right *= nums[i]
            return out
        """
    ),
    9: _code(
        """
        def merge(intervals):
            if not intervals:
                return []
            ordered = sorted(intervals, key=lambda pair: pair[0])
            out = [list(ordered[0])]
            for start, end in ordered[1:]:
                if start <= out[-1][1]:
                    out[-1][1] = max(out[-1][1], end)
                else:
                    out.append([start, end])
            return out
        """
    ),
    10: _code(
        """
        def lengthOfLongestSubstring(s):
            seen = {}
            best = 0
            start = 0
            for i, ch in enumerate(s):
                if ch in seen and seen[ch] >= start:
                    start = seen[ch] + 1
                seen[ch] = i
                best = max(best, i - start + 1)
            return best
        """
    ),
    11: _code(
        """
        def trap(height):
            if not height:
                return 0
            left, right = 0, len(height) - 1
            max_left, max_right = height[left], height[right]
            water = 0
            while left < right:
                if max_left <= max_right:
                    left += 1
                    max_left = max(max_left, height[left])
                    water += max_left - height[left]
                else:
                    right -= 1
                    max_right = max(max_right, height[right])
                    water += max_right - height[right]
            return water
        """
    ),
    12: _code(
        """
        def findMedianSortedArrays(nums1, nums2):
            merged = sorted(nums1 + nums2)
            n = len(merged)
            mid = n // 2
            if n % 2:
                return float(merged[mid])
            return (merged[mid - 1] + merged[mid]) / 2
        """
    ),
}

#: The same twelve solutions in JavaScript. Separate table rather than a
#: per-language dict inside one, because a missing entry should be a KeyError
#: naming the problem, not a silent skip.
REFERENCE_JS: dict[int, str] = {
    1: _code(
        """
        function containsDuplicate(nums) {
          return new Set(nums).size !== nums.length;
        }
        """
    ),
    2: _code(
        """
        function twoSum(nums, target) {
          const seen = new Map();
          for (let i = 0; i < nums.length; i++) {
            const need = target - nums[i];
            if (seen.has(need)) return [seen.get(need), i];
            seen.set(nums[i], i);
          }
          return [];
        }
        """
    ),
    3: _code(
        """
        function isAnagram(s, t) {
          const norm = (text) => text.split('').sort().join('');
          return norm(s) === norm(t);
        }
        """
    ),
    4: _code(
        """
        function search(nums, target) {
          let low = 0;
          let high = nums.length - 1;
          while (low <= high) {
            const mid = Math.floor((low + high) / 2);
            if (nums[mid] === target) return mid;
            if (nums[mid] < target) low = mid + 1;
            else high = mid - 1;
          }
          return -1;
        }
        """
    ),
    5: _code(
        """
        function maxSubArray(nums) {
          let best = nums[0];
          let current = nums[0];
          for (let i = 1; i < nums.length; i++) {
            current = Math.max(nums[i], current + nums[i]);
            best = Math.max(best, current);
          }
          return best;
        }
        """
    ),
    6: _code(
        """
        function isValid(s) {
          const pairs = { ')': '(', ']': '[', '}': '{' };
          const stack = [];
          for (const ch of s) {
            if (ch === '(' || ch === '[' || ch === '{') stack.push(ch);
            else if (stack.pop() !== pairs[ch]) return false;
          }
          return stack.length === 0;
        }
        """
    ),
    7: _code(
        """
        function groupAnagrams(strs) {
          const groups = new Map();
          for (const word of strs) {
            const key = word.split('').sort().join('');
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(word);
          }
          return Array.from(groups.values()).map((group) => group.slice().sort());
        }
        """
    ),
    8: _code(
        """
        function productExceptSelf(nums) {
          const n = nums.length;
          const out = new Array(n).fill(1);
          let left = 1;
          for (let i = 0; i < n; i++) {
            out[i] = left;
            left *= nums[i];
          }
          let right = 1;
          for (let i = n - 1; i >= 0; i--) {
            out[i] *= right;
            right *= nums[i];
          }
          return out;
        }
        """
    ),
    9: _code(
        """
        function merge(intervals) {
          if (intervals.length === 0) return [];
          const ordered = intervals.slice().sort((a, b) => a[0] - b[0]);
          const out = [ordered[0].slice()];
          for (const [start, end] of ordered.slice(1)) {
            const last = out[out.length - 1];
            if (start <= last[1]) last[1] = Math.max(last[1], end);
            else out.push([start, end]);
          }
          return out;
        }
        """
    ),
    10: _code(
        """
        function lengthOfLongestSubstring(s) {
          const seen = new Map();
          let best = 0;
          let start = 0;
          for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (seen.has(ch) && seen.get(ch) >= start) start = seen.get(ch) + 1;
            seen.set(ch, i);
            best = Math.max(best, i - start + 1);
          }
          return best;
        }
        """
    ),
    11: _code(
        """
        function trap(height) {
          if (height.length === 0) return 0;
          let left = 0;
          let right = height.length - 1;
          let maxLeft = height[left];
          let maxRight = height[right];
          let water = 0;
          while (left < right) {
            if (maxLeft <= maxRight) {
              left += 1;
              maxLeft = Math.max(maxLeft, height[left]);
              water += maxLeft - height[left];
            } else {
              right -= 1;
              maxRight = Math.max(maxRight, height[right]);
              water += maxRight - height[right];
            }
          }
          return water;
        }
        """
    ),
    12: _code(
        """
        function findMedianSortedArrays(nums1, nums2) {
          const merged = nums1.concat(nums2).sort((a, b) => a - b);
          const n = merged.length;
          const mid = Math.floor(n / 2);
          if (n % 2 === 1) return merged[mid];
          return (merged[mid - 1] + merged[mid]) / 2;
        }
        """
    ),
}

#: The demo solution: correct on the small cases, quadratic on the large one.
NAIVE = _code(
    """
    def containsDuplicate(nums):
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                if nums[i] == nums[j]:
                    return True
        return False
    """
)

#: The same quadratic solution in JavaScript. Kept separately rather than
#: translated on the fly, because the demo's headline number is asserted in both
#: languages and the two must be recognisably the same algorithm.
NAIVE_JS = _code(
    """
    function containsDuplicate(nums) {
      for (let i = 0; i < nums.length; i++) {
        for (let j = i + 1; j < nums.length; j++) {
          if (nums[i] === nums[j]) return true;
        }
      }
      return false;
    }
    """
)

PERF_CASE_NAME = "Large input (performance)"

#: A known-linear probe, one per language, for section 15.
#:
#: Deliberately **not** the problem's own optimal solution. That solution builds
#: a hash set, and the plan records that its growth is allocation-bound and
#: lumpy - 2.54x / 2.68x / 3.15x per doubling against an ideal 2.0x - so using
#: it as the "linear" side of a comparison measures the constant factors rather
#: than the algorithm. A plain accumulation over the same input has nothing to
#: allocate and nothing to rehash, so it reads as the linear baseline the
#: comparison needs.
#:
#: The returned value is wrong on purpose. A measurement never checks
#: correctness, and a probe that had to be *correct* would have to be a solution
#: - which is the thing being avoided.
LINEAR_PROBE = _code(
    """
    def containsDuplicate(nums):
        total = 0
        for value in nums:
            total += value
        return total
    """
)

LINEAR_PROBE_JS = _code(
    """
    function containsDuplicate(nums) {
      let total = 0;
      for (const value of nums) total += value;
      return total;
    }
    """
)

#: Span used by section 15 to check the ladder responds to n.
#:
#: Starts at 8,000 because that is the floor section 5b established for
#: JavaScript: below it V8 is still interpreting the inner loop and a naive
#: solution reads *sublinear*. Stops at 32,000 because the naive solution has to
#: be affordable to measure on the machines this runs on - at 64,000 it needs
#: ~2s idle and could not finish inside the budget at all on 2026-09-23, when
#: C: was full and the same code ran 34x slower than the recorded ladder.
#:
#: A wider span is *not* automatically better here: over 8,000 -> 64,000 the
#: separation between the naive solution and a linear probe got **worse**, not
#: better (25.6x against 18.4x), because a larger input is throttled harder by
#: the container's one-CPU quota, so each measurement is inflated by an amount
#: that depends on its own size.
SIGNAL_SIZES = (8_000, 32_000)

#: Wall-clock ceiling for a correct submission, per backend. **This is a
#: catastrophic-slowness guard, not a performance target** - the real structural
#: protection is the `docker run` count in section 3.
#:
#: These numbers were rewritten on 2026-09-22 after the original docker bound
#: (4s, from "measured 2.25-2.62s warm") proved unmeasurable: four consecutive
#: runs of the same submission gave 4.65s, 3.87s, 3.95s and 5.14s, and a suite
#: run under load hit 8.17s. The recorded 2.25-2.62s was a real measurement but
#: is not reproducible, so no tight bound can survive here.
#:
#: The two backends must stay separate regardless: the first version used the
#: docker figure for both, and the host backend failed it at 4.66s - correctly,
#: because a Windows process spawn costs 0.59-1.0s against ~0.26s in-container.
WALL_BUDGET: dict[str, float] = {"docker": 20.0, "subprocess": 20.0}

#: What each guard was measured against, quoted in the failure message. Kept
#: honest: these are observed ranges, not a claim about the steady state.
WALL_BASELINE: dict[str, str] = {
    # Cold starts are slower still while the image layers page in from the vhdx.
    # The first run after a daemon restart is always the slowest, which is why
    # the demo should start with a throwaway submission.
    "docker": "observed 3.9-8.2s, load-dependent; was 2.25-2.62s at phase 2",
    "subprocess": "observed 3.4-4.7s, ~0.9s of process spawn per case",
}

#: Ignores its input entirely. Used to prove ``compute`` is not measuring the
#: interpreter boot: over 16x the input this has to stay flat.
NOOP = "def containsDuplicate(nums):\n    return False\n"

#: The same two calibrations in JavaScript. Section 5b runs them because Phase
#: 5's classifier will face both languages, and a threshold tuned on CPython is
#: not obviously right for V8.
JS_NOOP = _code(
    """
    function containsDuplicate(nums) {
      return false;
    }
    """
)

#: A plain O(n) scan. Used to calibrate what "linear" reads as, because it has
#: no allocation behaviour of its own - unlike problem 1's reference solution,
#: which builds a hash set and is therefore a lumpy benchmark.
SCAN = "def containsDuplicate(nums):\n    return sum(nums) == -1\n"

#: The JavaScript twin of `SCAN`. Written as a loop rather than
#: `nums.reduce(...)` so it is the same shape of work as `sum(nums)`: a
#: callback per element is not the same measurement as a loop.
JS_SCAN = _code(
    """
    function containsDuplicate(nums) {
      let total = 0;
      for (let i = 0; i < nums.length; i++) total += nums[i];
      return total === -1;
    }
    """
)


def main() -> int:
    print("\n=== 1. Catalogue data ===")
    problem_problems = problem_data.validate_catalogue()
    check(not problem_problems, "problems.json is structurally sound", "; ".join(problem_problems) or "clean")

    case_problems = test_case_data.validate_test_cases()
    check(not case_problems, "test_cases.json is structurally sound", "; ".join(case_problems) or "clean")

    total_cases = sum(len(cases) for cases in test_case_data.TEST_CASES.values())
    check(
        len(problem_data.PROBLEMS) == 12 and total_cases == 49,
        "catalogue is 12 problems / 49 cases",
        f"{len(problem_data.PROBLEMS)} problems, {total_cases} cases",
    )

    # Both languages must be offered by every problem, or the language selector
    # shows an option that 400s. Checked here rather than in the catalogue
    # validator because it is a Phase 4 invariant: the validator allows a
    # partially migrated catalogue on purpose.
    missing_language = [
        (p["id"], language)
        for p in problem_data.PROBLEMS
        for language in ("python", "javascript")
        if language not in p["languages"]
    ]
    check(
        not missing_language,
        "every problem is offered in both Python and JavaScript",
        f"missing: {missing_language}" if missing_language else "12 problems x 2 languages",
    )

    # Every problem must have test cases, and every case must be reachable.
    orphans = [p["id"] for p in problem_data.PROBLEMS if not test_case_data.get_test_cases(p["id"])]
    check(not orphans, "every problem has test cases", f"orphans: {orphans}" if orphans else "none")

    orphan_cases = sorted(set(test_case_data.TEST_CASES) - {p["id"] for p in problem_data.PROBLEMS})
    check(
        not orphan_cases,
        "every test-case block belongs to a real problem",
        f"orphans: {orphan_cases}" if orphan_cases else "none",
    )

    print("\n=== 2. Reference solutions pass, in every language ===")
    # 24 submissions, each its own container, so this section dominates the
    # suite's runtime. Worth it: it is the only check that proves the entrypoint
    # names, the starters and the test data all agree, in both languages, with
    # no server, token or quota.
    for problem in problem_data.PROBLEMS:
        pid = problem["id"]
        for language, table in (("python", REFERENCE), ("javascript", REFERENCE_JS)):
            if language not in problem["languages"]:
                continue
            result = run_submission(problem, table[pid], language)
            check(
                result["status"] == "passed" and result["passed"] == result["total"],
                f"problem {pid} ({language})",
                f"{result['status']} {result['passed']}/{result['total']} in {result['execution_time']}s",
            )

    print("\n=== 3. The demo case (the number that must not move) ===")
    demo = problem_data.get_problem(1)
    assert demo is not None
    naive = run_submission(demo, NAIVE, "python")

    check(
        naive["status"] == "partial",
        "naive solution is a partial pass",
        f"status={naive['status']}",
    )
    check(
        (naive["passed"], naive["total"]) == (3, 4),
        "naive solution scores exactly 3/4",
        f"{naive['passed']}/{naive['total']}",
    )

    failed = [t["name"] for t in naive["tests"] if not t["passed"]]
    check(
        failed == [PERF_CASE_NAME],
        "only the performance case fails",
        f"failed: {failed}",
    )

    perf = next((t for t in naive["tests"] if t["name"] == PERF_CASE_NAME), None)
    check(
        perf is not None and perf["error_type"] == "timeout",
        "the performance case fails by timeout, not by wrong answer",
        f"error_type={perf and perf['error_type']} elapsed={perf and perf['elapsed']}s",
    )
    check(
        perf is not None and perf["elapsed"] >= 2.9,
        "the timeout is actually enforced at ~3s",
        f"elapsed={perf and perf['elapsed']}s",
    )

    # And the same number in JavaScript. This assertion is the *reason* the
    # performance case runs at n=200,000 rather than the n=20,000 it started at.
    #
    # It took two attempts to get there, and the second one is the instructive
    # part. V8 JITs a tight loop where CPython does not, so at 20,000 the naive
    # JavaScript solution finished in 0.47s, scored a full 4/4, and the demo's
    # story only worked if the student picked Python. Raising it to 100,000 was
    # measured as 7.7s - but that measurement was taken while the machine was
    # loaded (the suite took 3m07s that run, against 1m37s on an idle one, and
    # every problem came in about twice as fast). On an idle machine the naive
    # JavaScript solution runs n=100,000 in **2.64s against the 3s limit** - a
    # 10% margin, so it passes and this check fails.
    #
    # Measured 2026-09-23 on an idle machine, best of 2 (the machine is roughly
    # 3x kinder to this loop in JavaScript than in Python, so the two languages
    # need very different n to cross the same wall):
    #
    #   n         JS naive   x limit   JS optimal
    #   100,000     2.64s      0.9x      0.020s
    #   150,000     5.88s      2.0x      0.046s
    #   200,000    10.48s      3.5x      0.063s
    #   250,000    16.40s      5.5x      0.067s
    #
    # 200,000 gives a 3.5x margin while leaving the optimal solution 47x of
    # headroom, and costs a 1.4MB stdin payload rather than 673KB - outside
    # `compute`, so it does not touch what Phase 5 measures. The lesson is the
    # same one the wall-clock bounds taught: **never pick a threshold from a
    # measurement taken on a loaded machine.**
    naive_js = run_submission(demo, NAIVE_JS, "javascript")
    check(
        (naive_js["passed"], naive_js["total"]) == (3, 4),
        "the same solution scores exactly 3/4 in JavaScript",
        f"{naive_js['passed']}/{naive_js['total']}",
    )
    js_failed = [t["name"] for t in naive_js["tests"] if not t["passed"]]
    check(
        js_failed == [PERF_CASE_NAME],
        "and it is the same case that fails",
        f"failed: {js_failed}",
    )
    js_perf = next((t for t in naive_js["tests"] if t["name"] == PERF_CASE_NAME), None)
    check(
        js_perf is not None and js_perf["error_type"] == "timeout",
        "by the same mechanism, at the same limit",
        f"error_type={js_perf and js_perf['error_type']} elapsed={js_perf and js_perf['elapsed']}s",
    )

    # Phase 2's exit criterion, asserted rather than assumed - but the *bound*
    # was rewritten on 2026-09-22 after the original one proved unmeasurable.
    #
    # The first version asserted "under 4s, measured 2.25-2.62s warm". Re-running
    # the same submission four times in a row gave 4.65s, 3.87s, 3.95s and 5.14s,
    # with per-case `elapsed` drifting from 0.166s to 0.25-0.47s, and a full suite
    # run under load hit 8.17s. **The 2.25-2.62s figure is not reproducible on
    # this machine**, so no absolute wall-clock bound can be both tight enough to
    # mean something and stable enough not to cry wolf. A flaky assertion in the
    # pre-demo check is worse than no assertion, because it teaches you to ignore
    # failures.
    #
    # So the structural property - *one container per submission*, the decision
    # that keeps the sandbox affordable - is now asserted directly and
    # load-independently, by counting docker invocations. The wall-clock bound
    # survives only as a catastrophic-slowness guard.
    started = time.perf_counter()
    optimal = run_submission(demo, REFERENCE[1], "python")
    wall = time.perf_counter() - started
    check(
        optimal["status"] == "passed" and optimal["passed"] == 4,
        "the optimal solution passes all 4, including the large input",
        f"{optimal['status']} {optimal['passed']}/{optimal['total']} "
        f"in {optimal['execution_time']}s of case work, {wall:.2f}s wall clock",
    )
    check(
        wall < WALL_BUDGET[config.runner_backend()],
        "a correct submission finishes inside the catastrophic-slowness guard",
        f"{wall:.2f}s wall clock (guard {WALL_BUDGET[config.runner_backend()]}s on "
        f"{config.runner_backend()}; {WALL_BASELINE[config.runner_backend()]})",
    )
    check(
        max(t["compute"] for t in optimal["tests"]) < 0.05,
        "per-case compute stays well under 50ms",
        f"max compute={max(t['compute'] for t in optimal['tests']):.6f}s",
    )

    # The structural version of the same concern, and the one that actually
    # holds up. One container per submission is the whole reason the sandbox is
    # affordable: a container per case would be four times the lifecycle cost for
    # no isolation benefit. Counting `docker run` calls proves it regardless of
    # how loaded the machine is.
    if config.runner_backend() != "docker":
        record(SKIP, "one submission starts exactly one container", f"RUNNER_BACKEND={config.runner_backend()}")
    else:
        docker_calls: list[str] = []
        real_run = subprocess.run

        def counting_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            # `cmd` is always an argv list here; the runner never uses a shell.
            docker_calls.append(str(cmd[1]) if isinstance(cmd, (list, tuple)) and len(cmd) > 1 else "")
            return real_run(cmd, *args, **kwargs)

        subprocess.run = counting_run
        try:
            run_submission(demo, REFERENCE[1], "python")
        finally:
            subprocess.run = real_run

        creates = [c for c in docker_calls if c == "run"]
        removes = [c for c in docker_calls if c == "rm"]
        check(
            len(creates) == 1 and len(removes) <= 1,
            "one submission starts exactly one container",
            f"docker invocations: {len(creates)} run, {len(removes)} rm "
            f"(a container per case would be 4 run calls)",
        )

    print("\n=== 4. generate: the large input is real ===")
    # If `generate` silently produced an empty or tiny list, the nested-loop
    # solution would pass and the demo would lose its whole point.
    #
    # The size is 200,000 rather than the 20,000 it started at, and the reason
    # matters: the performance case has to make a quadratic solution fail in
    # *every* supported language, not just the slowest one. Measured
    # 2026-09-23, the naive JavaScript solution needs 10.48s at n=200,000
    # against the 3s limit (a 3.5x margin) while the optimal solution stays at
    # 0.063s. Section 3 carries the full ladder and the story of how the first
    # two attempts at this number were both wrong.
    perf_case = next((c for c in test_case_data.get_test_cases(1) if c.get("name") == PERF_CASE_NAME), None)
    expanded = test_case_data.resolve_args(perf_case) if perf_case else []
    check(
        len(expanded) == 1 and isinstance(expanded[0], list) and len(expanded[0]) == 200000,
        "generate.range expands to one 200,000-element argument",
        f"{len(expanded)} arg(s), first has {len(expanded[0]) if expanded else 0} elements",
    )
    check(
        expanded and expanded[0][:3] == [0, 1, 2] and expanded[0][-1] == 199999,
        "the generated list is 0..199999 in order",
        f"head={expanded[0][:3] if expanded else None} tail={expanded[0][-1] if expanded else None}",
    )

    print("\n=== 5. Per-case detail ===")
    elapsed = [t["elapsed"] for t in optimal["tests"]]
    check(
        all(isinstance(v, (int, float)) and v > 0 for v in elapsed),
        "every case reports a positive elapsed time",
        f"elapsed={elapsed}",
    )
    check(
        abs(optimal["execution_time"] - sum(elapsed)) < 0.01,
        "the total is the sum of the per-case times",
        f"total={optimal['execution_time']} sum={round(sum(elapsed), 3)}",
    )

    noisy = "def containsDuplicate(nums):\n    print('n =', len(nums))\n    return False\n"
    noisy_run = run_submission(demo, noisy, "python")
    printed = [t["stdout"] for t in noisy_run["tests"] if t.get("stdout")]
    check(
        len(printed) == 4 and "n = " in printed[0],
        "student stdout is captured per case",
        f"{len(printed)} case(s) carried output, first={printed[0]!r}" if printed else "none",
    )

    # `compute` must exclude interpreter startup, or it is useless: on this
    # machine spawning a process costs ~0.9s and a trivial solution costs
    # microseconds, so `elapsed` alone measures the wrong thing entirely.
    check(
        all(0 < t["compute"] < t["elapsed"] for t in optimal["tests"]),
        "compute is positive and well below elapsed",
        f"compute={[t['compute'] for t in optimal['tests']]} "
        f"elapsed={[t['elapsed'] for t in optimal['tests']]}",
    )
    check(
        all(t["compute"] < 0.05 for t in optimal["tests"]),
        "a correct solution computes in well under 50ms",
        f"max compute={max(t['compute'] for t in optimal['tests'])}s",
    )

    print("\n=== 5b. compute is a real signal (what phase 5 rests on) ===")

    def best_times(code: str, sizes: list[int], reps: int = 3, language: str = "python") -> list[float]:
        """Best-of-N ``compute`` per size, all sizes in one container.

        Best-of-N rather than the mean because the noise here is one-sided: a
        measurement is only ever slowed down by the machine, never sped up.
        One container for the whole ladder keeps the run affordable.

        Uses ``_execute`` rather than a backend-specific entry point so this
        section measures whichever backend is configured. Only ``compute`` is
        read, never ``elapsed``: the point is the student's own code, and with
        the docker backend ``elapsed`` would carry a container startup.
        """
        cases = [
            {
                "name": f"n={n}",
                "generate": {"kind": "range", "n": n},
                "expected": False,
                # Generous: this section measures growth, so a timeout would
                # turn a slow measurement into a missing one.
                "timeout": 60.0,
            }
            for n in sizes
        ]
        best = [float("inf")] * len(sizes)
        for _ in range(reps):
            outcomes = code_runner._execute(cases, code, "containsDuplicate", language).outcomes
            for index, (outcome, _elapsed) in enumerate(outcomes):
                best[index] = min(best[index], float(outcome.get("compute") or 0.0))
        return best

    def per_doubling(times: list[float], sizes: list[int]) -> float:
        """Growth per doubling of input, averaged over the whole ladder.

        Exponentiating the total growth spreads the noise over every doubling
        instead of resting on one adjacent pair. Measured 2026-09-22, pairwise
        ratios for a linear solution came out 2.63, 1.64, 2.74, 1.31 - any one
        pair can read as ~1.0. Phase 5's classifier must average the same way.
        """
        doublings = math.log2(sizes[-1] / sizes[0])
        return (times[-1] / max(times[0], 1e-12)) ** (1 / doublings)

    # A. compute must not be measuring the interpreter boot. This is the whole
    #    reason the field exists: on the host, `elapsed` is ~0.9s of process
    #    spawn around ~20us of work, so a function that ignores its input
    #    entirely has to come out flat.
    noop_sizes = [3000, 48000]
    noop = best_times(NOOP, noop_sizes)
    noop_growth = noop[-1] / max(noop[0], 1e-12)
    check(
        noop_growth < 3.0,
        "compute excludes interpreter startup (a no-op stays flat over 16x input)",
        f"n=3000 -> n=48000 grows {noop_growth:.2f}x "
        f"({noop[0] * 1e6:.1f}us -> {noop[-1] * 1e6:.1f}us)",
    )

    # B. A plain scan must read as linear. `sum(nums)` is the calibration
    #    reference rather than problem 1's own reference solution, which builds
    #    a hash set: measured over the same ladder, `set(nums)` came out at
    #    2.54x/2.68x/3.15x per doubling against an ideal 2.0x, because growing
    #    a hash table is allocation-bound and rehashes in steps. A benchmark
    #    that is itself irregular cannot calibrate anything.
    scan_sizes = [3000, 48000]
    scan_per_doubling = per_doubling(best_times(SCAN, scan_sizes), scan_sizes)
    check(
        1.5 < scan_per_doubling < 2.6,
        "a plain scan of the input reads as linear",
        f"n=3000 -> n=48000 gives {scan_per_doubling:.2f}x per doubling (O(n) predicts 2x)",
    )

    # C. The naive demo solution must read as clearly superlinear. This is
    #    stable: measured 4.09x and 4.12x against an ideal 4.0x.
    quad_sizes = [1000, 8000]
    quad_per_doubling = per_doubling(best_times(NAIVE, quad_sizes, reps=2), quad_sizes)
    check(
        quad_per_doubling > 3.5,
        "the naive demo solution reads as clearly superlinear",
        f"n=1000 -> n=8000 gives {quad_per_doubling:.2f}x per doubling (O(n^2) predicts 4x)",
    )

    # D. And the two have to be far enough apart for a classifier to pick a
    #    side. The margin is real but not enormous - this is the honest
    #    ceiling on what timing alone can prove, and it is why phase 5 pairs
    #    the measurement with a static read of the code.
    check(
        quad_per_doubling > scan_per_doubling * 1.5,
        "linear and quadratic are far enough apart to classify",
        f"quadratic {quad_per_doubling:.2f}x vs linear {scan_per_doubling:.2f}x per doubling",
    )

    # E. The same calibrations in JavaScript, because Phase 5's classifier will
    #    face both languages and a threshold tuned on CPython is not obviously
    #    right for V8. It is not.
    #
    #    **The JavaScript ladder starts at 8,000, not at Python's 1,000, and the
    #    reason is a real difference between the runtimes rather than a
    #    convenience.** Measured 2026-09-22, the naive solution's per-doubling
    #    ratio was 1.31 and 1.86 over n=1,000..8,000, against 3.04, 3.69, 3.47
    #    and 3.97 over n=8,000..64,000 - the small end reads as *sublinear*.
    #    The cause is JIT warmup: the same inner loop runs about ten times
    #    faster per comparison once TurboFan has optimized it, and that speedup
    #    very nearly cancels the quadratic growth at small n. CPython has no
    #    equivalent regime change, which is exactly why its ladder can start low
    #    and this one cannot.
    #
    #    Raw measurements behind those numbers (compute, best of 2, one
    #    container per rep, ms):
    #      n      1000    2000    4000    8000    16000   32000   64000
    #      naive   5.31    6.93   12.90   39.25   144.93  503.45  1997.32
    #      scan    0.37     -       -      1.32      -       -      3.36
    #      no-op   0.27     -       -      0.25      -       -      0.24
    #
    #    The no-op is flat across the whole range, so `compute` is not leaking
    #    container or interpreter time - the floor is a genuine ~0.24ms of
    #    per-case vm setup, which is the JS counterpart of Python's 5us.
    js_quad_sizes = [8000, 64000]
    js_quad_per_doubling = per_doubling(best_times(NAIVE_JS, js_quad_sizes, reps=2, language="javascript"), js_quad_sizes)
    check(
        js_quad_per_doubling > 3.0,
        "the naive demo solution reads as clearly superlinear in JavaScript",
        f"n=8000 -> n=64000 gives {js_quad_per_doubling:.2f}x per doubling (O(n^2) predicts 4x; "
        f"n=1000 -> n=8000 reads sublinear because V8 is still interpreting there)",
    )

    js_noop_sizes = [8000, 64000]
    js_noop = best_times(JS_NOOP, js_noop_sizes, reps=2, language="javascript")
    js_noop_growth = js_noop[-1] / max(js_noop[0], 1e-12)
    check(
        js_noop_growth < 3.0,
        "compute excludes the vm setup too (a JS no-op stays flat over 8x input)",
        f"n=8000 -> n=64000 grows {js_noop_growth:.2f}x "
        f"({js_noop[0] * 1e6:.1f}us -> {js_noop[-1] * 1e6:.1f}us)",
    )

    # Only the *upper* bound is asserted here, and that is deliberate rather
    # than lazy. A linear solution must not read as superlinear - that is the
    # error that would make the classifier lie to a student - but a reading
    # slightly *below* 2x is expected in JavaScript for the same JIT reason, so
    # a lower bound would be asserting that the machine is cold. The number is
    # reported either way, and the separation below is what Phase 5 rests on.
    js_scan_sizes = [8000, 64000]
    js_scan_per_doubling = per_doubling(best_times(JS_SCAN, js_scan_sizes, reps=2, language="javascript"), js_scan_sizes)
    check(
        js_scan_per_doubling < 2.6,
        "a plain scan of the input does not read as superlinear in JavaScript",
        f"n=8000 -> n=64000 gives {js_scan_per_doubling:.2f}x per doubling "
        f"(O(n) predicts 2x; below it is JIT warmup, not an algorithm)",
    )

    # The margin is smaller in JavaScript than in Python (measured 3.70x against
    # 1.36x) because the linear end reads low. 1.8x of separation is still a
    # clear gap for a classifier to sit in, and it is the number Phase 5 should
    # be built against rather than the Python one.
    check(
        js_quad_per_doubling > js_scan_per_doubling * 1.8,
        "and the two are separable in JavaScript as well as in Python",
        f"quadratic {js_quad_per_doubling:.2f}x vs linear {js_scan_per_doubling:.2f}x per doubling",
    )

    print("\n=== 6. Errors are friendly and specific ===")
    syntax = run_submission(demo, "def containsDuplicate(nums)\n    return False\n", "python")
    check(
        syntax["status"] == "error" and syntax["error"] and syntax["error"]["type"] == "syntax",
        "syntax error is reported as such",
        f"{syntax['status']} / {syntax['error'] and syntax['error']['title']}",
    )
    check(
        syntax["error"] is not None and syntax["error"]["line"] is not None,
        "syntax error names a line",
        f"line={syntax['error'] and syntax['error']['line']}",
    )

    missing = run_submission(demo, "def wrongName(nums):\n    return False\n", "python")
    message = (missing["error"] or {}).get("detail", "")
    check(
        missing["status"] == "error" and "containsDuplicate" in message,
        "a missing entrypoint is named in the error",
        message[:100],
    )

    runtime = run_submission(demo, "def containsDuplicate(nums):\n    return nums[99]\n", "python")
    check(
        runtime["status"] == "error" and runtime["error"] and runtime["error"]["type"] == "runtime",
        "a runtime exception is reported as such",
        f"{runtime['status']} / {runtime['error'] and runtime['error']['type']}",
    )

    print("\n=== 7. Comparison rules ===")
    check(_values_match(4, 4.0), "int matches float", "4 == 4.0")
    check(_values_match((0, 1), [0, 1]), "tuple matches list", "(0, 1) == [0, 1]")
    check(not _values_match([0, 1], [1, 0]), "order matters by default", "[0,1] != [1,0]")
    check(_compare([0, 1], [1, 0], "unordered"), "unordered comparator ignores order", "[0,1] ~ [1,0]")
    check(not _compare([0, 1], [1, 2], "unordered"), "unordered still checks values", "[0,1] !~ [1,2]")
    check(_values_match(True, True) and _values_match(False, False), "booleans compare", "True/False")
    check(not _values_match(True, False), "True does not match False", "True != False")

    print("\n=== 8. Language refusals ===")
    try:
        resolve_language(demo, "cobol")
        check(False, "an unknown language is refused", "no exception raised")
    except UnsupportedLanguage as exc:
        check(True, "an unknown language is refused", str(exc))

    check(
        resolve_language(demo, "python3") == "python" and resolve_language(demo, "PY") == "python",
        "language aliases normalise to python",
        "python3, PY -> python",
    )

    print("\n=== 9. The API never leaks the answers ===")
    public = problem_data.to_public(demo)
    detail = problem_data.to_public(demo, include_languages=True)
    check(
        not any(k in public for k in ("languages", "starter", "entrypoint")),
        "the list projection carries no starter or signature",
        f"keys={sorted(public)}",
    )
    check(
        set(detail) - set(public) == {"languages"},
        "the detail projection adds only languages",
        f"added={sorted(set(detail) - set(public))}",
    )
    check(
        not any(k in detail for k in ("test_cases", "expected", "hidden")),
        "no test data appears in either projection",
        "clean",
    )

    print("\n=== 10. The sandbox actually isolates (docker backend only) ===")

    if config.runner_backend() != "docker":
        record(
            SKIP,
            "sandbox isolation probes",
            f"RUNNER_BACKEND={config.runner_backend()} - there is no sandbox to probe",
        )
    else:

        def probe(code: str, timeout: float = 5.0) -> dict:
            """Run one throwaway case and return the raw outcome."""
            case = {"name": "isolation probe", "args": [[]], "expected": False, "timeout": timeout}
            outcome, _elapsed = code_runner._execute(
                [case], code, "containsDuplicate"
            ).outcomes[0]
            return outcome

        # Network. If --network none were dropped, create_connection would
        # succeed, the probe would return False, and "passed" would be True -
        # so a passing probe here is the failure. Checking the message as well
        # distinguishes "blocked" from "failed for an unrelated reason".
        net = probe(
            "import socket\n"
            "def containsDuplicate(nums):\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
            "    return False\n"
        )
        net_message = net.get("message") or ""
        check(
            not net.get("passed") and "unreachable" in net_message.lower(),
            "student code cannot reach the network",
            net_message or "the probe passed - the sandbox reached the internet",
        )

        # Memory. A child killed by the cgroup OOM killer writes nothing at
        # all, so this also guards the message: "no result" would be true and
        # useless.
        mem = probe(
            "def containsDuplicate(nums):\n"
            "    blocks = []\n"
            "    while True:\n"
            "        blocks.append(bytearray(64 * 1024 * 1024))\n",
            timeout=15.0,
        )
        mem_message = mem.get("message") or ""
        check(
            not mem.get("passed") and "memory" in mem_message.lower(),
            "a submission that exhausts memory is stopped, and is told why",
            mem_message or "the probe passed - the memory ceiling is not enforced",
        )

        # Time. The per-case timeout has to kill the child, not the container,
        # or one slow case would lose every case after it.
        slow = probe("def containsDuplicate(nums):\n    while True:\n        pass\n", timeout=2.0)
        check(
            not slow.get("passed") and slow.get("error_type") == "timeout",
            "an infinite loop is killed at the per-case timeout",
            f"error_type={slow.get('error_type')} message={slow.get('message')}",
        )

        # Lifecycle. subprocess.run(timeout=) kills the docker CLI, not the
        # container, so a timeout would otherwise leak a container per run.
        leaked = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                config.DOCKER_BINARY,
                "ps",
                "-a",
                "--filter",
                "name=codereviewer-run-",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        names = [n for n in (leaked.stdout or "").split() if n]
        check(
            not names,
            "no container outlives its request",
            f"leaked: {names}" if names else "none",
        )

    print("\n=== 11. Sentinel parity: the host and both sandboxes must agree ===")
    # These literals are duplicated by necessity - a sandbox script cannot be
    # imported from the API and vice versa - and drifting on either one fails
    # *silently and totally*. A RESULT_SENTINEL mismatch makes every submission
    # report "produced no result" while the runs themselves succeed; a
    # SANDBOX_SENTINEL mismatch makes the sandbox facts quietly disappear from
    # every response. Neither shows up as an exception anywhere.
    #
    # Adding a second language took RESULT_SENTINEL from three copies to five
    # and SANDBOX_SENTINEL from two to three, so this section is now the only
    # thing between a copy-paste slip and a runner that silently reports
    # nothing.
    repo_root = Path(__file__).resolve().parent.parent.parent

    python_entry = repo_root / "docker" / "runner-python" / "entrypoint.py"
    node_entry = repo_root / "docker" / "runner-node" / "entrypoint.js"
    check(
        python_entry.exists() and node_entry.exists(),
        "both container entrypoints are where this check expects them",
        f"{python_entry.name}, {node_entry.name}",
    )

    py_entry = _load_module(python_entry)
    py_harness = _load_module(Path(code_runner.HARNESS_PATH))
    # Python cannot import a JavaScript module, so the JavaScript side is read
    # as text - see `_js_constants` for why that is restricted to exact
    # literals, and note that a key it could not find comes out as ``None``
    # here, which fails the check rather than passing it.
    js_harness = _js_constants(Path(code_runner.NODE_HARNESS_PATH))
    js_entry = _js_constants(node_entry)

    # Five-way, because all five touch this line: each harness writes it inside
    # its child, each entrypoint parses it in its container, and the API parses
    # it on the host.
    sentinels = {
        "python harness": py_harness.RESULT_SENTINEL,
        "python entrypoint": py_entry.RESULT_SENTINEL,
        "api": code_runner.RESULT_SENTINEL,
        "js harness": js_harness.get("RESULT_SENTINEL"),
        "js entrypoint": js_entry.get("RESULT_SENTINEL"),
    }
    check(
        None not in sentinels.values() and len(set(sentinels.values())) == 1,
        "RESULT_SENTINEL is identical in all five files that touch it",
        " ".join(f"{name}={value!r}" for name, value in sentinels.items()),
    )

    sandbox_sentinels = {
        "python entrypoint": py_entry.SANDBOX_SENTINEL,
        "api": code_runner.SANDBOX_SENTINEL,
        "js entrypoint": js_entry.get("SANDBOX_SENTINEL"),
    }
    check(
        None not in sandbox_sentinels.values() and len(set(sandbox_sentinels.values())) == 1,
        "SANDBOX_SENTINEL is identical in all three files that touch it",
        " ".join(f"{name}={value!r}" for name, value in sandbox_sentinels.items()),
    )

    # The output caps have to match across languages too, or the same student
    # printing the same 10,000 lines gets a different answer depending on which
    # language they picked. Section 12 reads its bound from the Python harness,
    # so a drift here would leave the JavaScript one unmeasured.
    check(
        str(py_harness.MAX_CAPTURED_CHARS) == js_harness.get("MAX_CAPTURED_CHARS")
        and str(py_harness.MAX_REPR_CHARS) == js_harness.get("MAX_REPR_CHARS"),
        "both harnesses cap stdout and reprs at the same sizes",
        f"captured python={py_harness.MAX_CAPTURED_CHARS} js={js_harness.get('MAX_CAPTURED_CHARS')}, "
        f"repr python={py_harness.MAX_REPR_CHARS} js={js_harness.get('MAX_REPR_CHARS')}",
    )
    check(
        py_harness.TRUNCATION_MARKER == js_harness.get("TRUNCATION_MARKER"),
        "and they mark a truncated line identically, byte for byte",
        f"{py_harness.TRUNCATION_MARKER!r}",
    )

    # The images are built from the repo root precisely so neither harness is
    # *duplicated* - there is one file per language, and both the container and
    # the host backend run it. If a COPY line ever pointed somewhere else, the
    # subprocess backend would keep passing while the sandboxed one silently ran
    # a stale harness.
    runtimes = {
        "python": {
            "entrypoint": python_entry,
            "harness": Path(code_runner.HARNESS_PATH),
            "copies": [("backend/app/services/_runner_harness.py", py_entry.HARNESS_PATH)],
            "image": config.runner_image("python"),
        },
        "javascript": {
            "entrypoint": node_entry,
            "harness": Path(code_runner.NODE_HARNESS_PATH),
            "copies": [
                ("docker/runner-node/harness.js", "/opt/runner/harness.js"),
                ("docker/runner-node/entrypoint.js", "/opt/runner/entrypoint.js"),
            ],
            "image": config.runner_image("javascript"),
        },
    }

    for language, spec in runtimes.items():
        dockerfile = spec["entrypoint"].parent / "Dockerfile"
        dockerfile_text = dockerfile.read_text(encoding="utf-8") if dockerfile.exists() else ""
        check(
            dockerfile.exists(),
            f"the {language} image has a Dockerfile beside its entrypoint",
            str(dockerfile.relative_to(repo_root).as_posix()),
        )
        missing_copies = [
            f"COPY {source} {destination}"
            for source, destination in spec["copies"]
            if f"COPY {source} {destination}" not in dockerfile_text
        ]
        check(
            not missing_copies,
            f"the {language} image installs every file exactly where its entrypoint looks",
            f"missing: {missing_copies}"
            if missing_copies
            else "; ".join(f"{source} -> {destination}" for source, destination in spec["copies"]),
        )
        # The build context is the repo root, so the COPY source is a repo
        # path - which means it can be compared against the path the host
        # backend executes. This is the assertion that there is genuinely one
        # harness per language rather than one file and one stale copy.
        installed = (repo_root / spec["copies"][0][0]).resolve()
        check(
            installed == spec["harness"].resolve(),
            f"the {language} image bakes in the same harness the host backend runs, not a copy",
            f"{spec['copies'][0][0]} == {spec['harness'].relative_to(repo_root).as_posix()}",
        )

    # Staleness. The sandbox runs a *baked-in* copy of its harness, so editing
    # the source without rebuilding means the tests keep exercising the old code
    # - and the failure is silent, because the old code still works. This is the
    # same class of trap as a stale uvicorn, and it has already bitten once: an
    # image built at 13:41 ran a harness edited at 13:49, which is how the
    # truncated-output check in section 12 first failed.
    if config.runner_backend() != "docker":
        record(
            SKIP,
            "the sandbox images are newer than the code they run",
            f"RUNNER_BACKEND={config.runner_backend()}",
        )
    else:
        for language, spec in runtimes.items():
            built = _image_created_at(spec["image"])
            newest = max(
                datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                for path in (spec["entrypoint"], spec["harness"])
            )
            if built is None:
                record(
                    SKIP,
                    f"the {language} image is newer than its sources",
                    f"could not read {spec['image']}'s build time",
                )
                continue
            rebuild = (
                ""
                if built >= newest
                else f" - REBUILD: docker build -f {spec['entrypoint'].parent.relative_to(repo_root).as_posix()}"
                f"/Dockerfile -t {spec['image']} ."
            )
            check(
                built >= newest,
                f"the {language} image is newer than the sources it runs",
                f"{spec['image']} built {built:%Y-%m-%d %H:%M:%S}Z, newest source "
                f"{newest:%Y-%m-%d %H:%M:%S}Z{rebuild}",
            )

    print("\n=== 12. Phase 3: what the student is told when it goes wrong ===")
    # Phase 3's exit criteria, asserted rather than eyeballed:
    #   "a submission that prints 10,000 lines shows bounded output instead of
    #    hanging the page; a wrong-answer case shows a readable diff; a killed
    #    submission says it was killed and why."

    # A. Bounded output. Both halves matter: bounded, so the response cannot
    #    grow without limit; and honest, so the student is told the output was
    #    cut rather than shown the first 4,000 characters as if they were all
    #    of it. The bound is read from the harness rather than hardcoded, which
    #    also catches "edited the harness but forgot to rebuild the image" -
    #    the container runs a baked-in copy, so a stale image shows up here.
    bound = py_harness.MAX_CAPTURED_CHARS + len(py_harness.TRUNCATION_MARKER)
    chatty = (
        "def containsDuplicate(nums):\n"
        "    for i in range(10000):\n"
        "        print('line', i)\n"
        "    return False\n"
    )
    loud = run_submission(demo, chatty, "python")
    lengths = [len(t.get("stdout") or "") for t in loud["tests"]]
    check(
        all(0 < n <= bound for n in lengths),
        "10,000 printed lines come back bounded, not unbounded",
        f"lengths={lengths} (bound {bound} from the harness)",
    )
    check(
        all(t.get("stdout_truncated") for t in loud["tests"]),
        "and every case says its output was cut, instead of trailing off",
        f"truncated={[bool(t.get('stdout_truncated')) for t in loud['tests']]}",
    )
    import json as _json  # noqa: PLC0415 - only needed for this measurement

    payload_size = len(_json.dumps(loud))
    check(
        payload_size < 40000,
        "the whole response stays small even when the student prints a lot",
        f"{payload_size} bytes across {loud['total']} cases",
    )

    # And the same cap in JavaScript, because it is enforced by a completely
    # different harness written in a different language. Section 11 says the two
    # constants agree; this says the JavaScript one is actually wired up, which
    # is the half a constant comparison cannot prove.
    js_loud = run_submission(
        demo,
        _code(
            """
            function containsDuplicate(nums) {
              for (let i = 0; i < 10000; i++) console.log('line', i);
              return false;
            }
            """
        ),
        "javascript",
    )
    js_lengths = [len(t.get("stdout") or "") for t in js_loud["tests"]]
    check(
        all(0 < n <= bound for n in js_lengths) and all(t.get("stdout_truncated") for t in js_loud["tests"]),
        "the JavaScript harness bounds output at the same cap, and says so",
        f"lengths={js_lengths} truncated={[bool(t.get('stdout_truncated')) for t in js_loud['tests']]}",
    )

    # B. A wrong answer has to arrive as data the UI can diff, not as a repr
    #    the frontend would have to re-parse. Reversing the returned pair makes
    #    every case fail on a list, which is exactly the diff the UI draws.
    reversed_pair = (
        "def twoSum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        if target - n in seen:\n"
        "            return [i, seen[target - n]]\n"
        "        seen[n] = i\n"
        "    return []\n"
    )
    swapped = run_submission(problem_data.get_problem(2), reversed_pair, "python")
    wrong = next((t for t in swapped["tests"] if not t["passed"]), None)
    check(
        wrong is not None
        and isinstance(wrong.get("expected_value"), list)
        and isinstance(wrong.get("actual_value"), list)
        and wrong["expected_value"] != wrong["actual_value"],
        "a wrong answer arrives as two structured values that differ",
        f"expected={wrong and wrong.get('expected_value')} "
        f"actual={wrong and wrong.get('actual_value')}",
    )
    check(
        wrong is not None and bool(wrong.get("expected")) and bool(wrong.get("actual")),
        "the reprs still travel as the fallback for non-JSON values",
        f"expected={wrong and wrong.get('expected')!r} actual={wrong and wrong.get('actual')!r}",
    )

    # C. Out of memory has to be *known*, not inferred. Without the cgroup's own
    #    oom_kill counter a SIGKILL is indistinguishable from a dozen other
    #    causes, and the message the student gets would be generic.
    #
    #    Docker-only, and the *run itself* is gated, not just the assertion: on
    #    the host there is no cgroup to stop this, so the probe would eat all
    #    the machine's memory and freeze it. The host backend cannot be probed
    #    for an OOM, only skipped.
    if config.runner_backend() != "docker":
        record(
            SKIP,
            "an out-of-memory submission is reported as such",
            f"RUNNER_BACKEND={config.runner_backend()} - no cgroup to read, and no ceiling to stop the probe",
        )
    else:
        oom_code = (
            "def containsDuplicate(nums):\n"
            "    blocks = []\n"
            "    while True:\n"
            "        blocks.append(bytearray(64 * 1024 * 1024))\n"
        )
        oom_case = {"name": "memory probe", "args": [[1, 2, 3, 1]], "expected": True, "timeout": 15.0}
        execution = code_runner._execute([oom_case], oom_code, "containsDuplicate")
        oom_outcome, _oom_elapsed = execution.outcomes[0]
        oom_sandbox = execution.sandbox or {}

        check(
            oom_outcome.get("oom_killed") is True
            and oom_outcome.get("signal") == 9
            and oom_outcome.get("exit_code") is None,
            "an out-of-memory child is reported as oom_killed, not as a bare SIGKILL",
            f"oom_killed={oom_outcome.get('oom_killed')} signal={oom_outcome.get('signal')} "
            f"exit_code={oom_outcome.get('exit_code')}",
        )
        check(
            "memory" in (oom_outcome.get("message") or "").lower(),
            "and the message names memory, not just 'stopped'",
            oom_outcome.get("message") or "no message",
        )
        limit = oom_sandbox.get("memory_limit_bytes") or 0
        peak = oom_sandbox.get("memory_peak_bytes") or 0
        check(
            oom_sandbox.get("oom_killed") is True and peak > limit * 0.9 > 0,
            "the sandbox reports the ceiling and the peak that reached it",
            f"peak={peak} limit={limit}",
        )

    # D. The flag has to be definitive on the sandboxed path - False, not
    #    absent - or the UI cannot tell "did not run out of memory" from "was
    #    never measured". The host backend says None and means it.
    normal_case = {"name": "normal probe", "args": [[1, 2, 3, 1]], "expected": True, "timeout": 5.0}
    normal = code_runner._execute([normal_case], REFERENCE[1], "containsDuplicate")
    normal_outcome, _normal_elapsed = normal.outcomes[0]

    if config.runner_backend() == "docker":
        check(
            normal_outcome.get("oom_killed") is False and normal_outcome.get("exit_code") == 0,
            "a clean case reports oom_killed=False and exit_code=0",
            f"oom_killed={normal_outcome.get('oom_killed')} exit_code={normal_outcome.get('exit_code')}",
        )
        check(
            normal.sandbox is not None,
            "the docker backend reports submission-level sandbox facts",
            f"keys={sorted(normal.sandbox or {})}",
        )
    else:
        check(
            normal_outcome.get("oom_killed") is None and normal_outcome.get("exit_code") == 0,
            "the host backend says oom_killed=None rather than pretending it measured it",
            f"oom_killed={normal_outcome.get('oom_killed')} exit_code={normal_outcome.get('exit_code')}",
        )
        check(
            normal.sandbox is None,
            "the host backend reports no sandbox facts instead of inventing them",
            "sandbox=None",
        )

    # E. And all of it has to survive the response shaping, or the UI never
    #    sees it. Checked on a real submission rather than the raw outcome.
    missing_keys = [
        key
        for key in ("exit_code", "signal", "oom_killed", "expected_value", "actual_value")
        if any(key not in t for t in optimal["tests"])
    ]
    check(
        not missing_keys,
        "every case in the API response carries the new execution metadata",
        f"missing: {missing_keys}" if missing_keys else f"{len(optimal['tests'])} cases complete",
    )

    # F. The route returns a plain dict and FastAPI validates it against
    #    ``response_model=RunResponse``, so a field name that drifts between
    #    run_submission and the schema is invisible to every check above - the
    #    runner is correct, the response is a 500 - and equally invisible to
    #    tsc, whose types are hand-written and cannot see the Python model.
    #    Validating the real payload against the real model closes that gap
    #    with no server, no token and no database.
    try:
        validated = RunResponse.model_validate(optimal)
    except ValidationError as exc:
        check(False, "the run payload satisfies the response model FastAPI enforces", str(exc)[:300])
    else:
        check(
            True,
            "the run payload satisfies the response model FastAPI enforces",
            f"{validated.status} {validated.passed}/{validated.total}, {len(validated.tests)} tests",
        )
        required = {"actual_value", "expected_value", "exit_code", "signal", "oom_killed", "stdout_truncated"}
        present = set(validated.tests[0].model_dump())
        check(
            required <= present,
            "every phase 3 field survives into the JSON the UI actually receives",
            f"missing: {sorted(required - present)}" if required - present else f"{len(present)} fields per test",
        )
        if config.runner_backend() == "docker":
            check(
                validated.sandbox is not None and bool(validated.sandbox.memory_limit_bytes),
                "and the sandbox facts arrive as a typed object, not a loose dict",
                f"limit={validated.sandbox and validated.sandbox.memory_limit_bytes} "
                f"peak={validated.sandbox and validated.sandbox.memory_peak_bytes}",
            )
        else:
            check(
                validated.sandbox is None,
                "the host backend validates with sandbox=None rather than a phantom object",
                "sandbox=None",
            )

    print("\n=== 13. Saved drafts are per (user, problem, language) ===")
    # Phase 4 added the language selector, which made "one draft per (user,
    # problem)" wrong: a Python draft and a JavaScript draft for the same
    # problem are two different pieces of work. With the old key, switching the
    # selector would have loaded the other language's code into the editor.
    #
    # Nothing else covered this. `smoke_test.py` has no saved-code checks at
    # all, and these routes are plain `def` handlers that FastAPI calls - so the
    # only way to exercise them without a server and a Clerk token is to call
    # them directly, which is what this does. It creates and deletes its own
    # throwaway user, so it is safe against the real database.
    database_ok, database_error = db.check_database()
    if not database_ok:
        record(
            SKIP,
            "a draft is stored per (user, problem, language)",
            f"no database: {database_error}",
        )
    else:
        marker = f"check-runner-{int(time.time())}"
        with db.SessionLocal() as session:
            user = User(clerk_user_id=marker)
            session.add(user)
            session.commit()
            session.refresh(user)
            uid = user.id

            try:
                py_code = "def containsDuplicate(nums):\n    return len(set(nums)) != len(nums)\n"
                js_code = "function containsDuplicate(nums) {\n  return false;\n}\n"

                py_saved = put_saved_code(1, SavedCodeIn(code=py_code, language="python"), user, session)
                js_saved = put_saved_code(1, SavedCodeIn(code=js_code, language="javascript"), user, session)

                # The whole point of the migration: two rows, not one row
                # overwritten. Before Phase 4 the second call clobbered the first.
                rows = session.scalars(
                    sa_select(SavedCode).where(SavedCode.user_id == uid, SavedCode.problem_id == 1)
                ).all()
                check(
                    len(rows) == 2,
                    "writing a draft in two languages keeps both, rather than one overwriting the other",
                    f"{len(rows)} row(s): {sorted(r.language for r in rows)}",
                )

                read_py = get_saved_code(1, user, session, "python")
                read_js = get_saved_code(1, user, session, "javascript")
                check(
                    read_py["code"] == py_code and read_js["code"] == js_code,
                    "and each language reads back its own code",
                    f"python={len(read_py['code'] or '')} chars, javascript={len(read_js['code'] or '')} chars",
                )

                # An alias must land on the existing row, not create a third.
                alias = get_saved_code(1, user, session, "js")
                alias_rows = session.scalar(
                    sa_select(sa_func.count())
                    .select_from(SavedCode)
                    .where(SavedCode.user_id == uid, SavedCode.problem_id == 1)
                )
                check(
                    alias["language"] == "javascript" and alias["code"] == js_code and alias_rows == 2,
                    "the alias 'js' reads the 'javascript' draft instead of creating a third row",
                    f"resolved to {alias['language']!r}, still {alias_rows} rows",
                )

                # Re-saving one language replaces in place.
                changed = py_code + "# edited\n"
                put_saved_code(1, SavedCodeIn(code=changed, language="python"), user, session)
                after = session.scalars(
                    sa_select(SavedCode).where(SavedCode.user_id == uid, SavedCode.problem_id == 1)
                ).all()
                by_language = {r.language: r for r in after}
                check(
                    len(after) == 2 and by_language["python"].code == changed,
                    "re-saving one language updates it in place",
                    f"{len(after)} rows, python={len(by_language['python'].code)} chars",
                )

                # The routes return plain dicts, exactly like the submission
                # routes - so a field-name drift is invisible to both `tsc` and
                # the handler itself. Validate against the real model.
                try:
                    validated_draft = SavedCodeOut.model_validate(read_js)
                except ValidationError as exc:
                    check(False, "the draft payload satisfies the response model", str(exc)[:300])
                else:
                    check(
                        validated_draft.problem_id == 1 and validated_draft.language == "javascript",
                        "the draft payload satisfies the response model the route declares",
                        f"problem_id={validated_draft.problem_id} language={validated_draft.language!r}",
                    )

                # 404 for a problem that is not in the catalogue, so a typo
                # cannot create an orphan row nothing can read back.
                try:
                    put_saved_code(9999, SavedCodeIn(code="x", language="python"), user, session)
                except HTTPException as exc:
                    check(
                        exc.status_code == 404,
                        "a draft for an unknown problem is refused",
                        f"HTTP {exc.status_code}",
                    )
                else:
                    check(False, "a draft for an unknown problem is refused", "no exception raised")

                # 400 for a language the runner cannot execute.
                try:
                    get_saved_code(1, user, session, "cobol")
                except HTTPException as exc:
                    check(
                        exc.status_code == 400,
                        "a draft in a language the runner cannot run is refused",
                        f"HTTP {exc.status_code}: {exc.detail}",
                    )
                else:
                    check(False, "a draft in a language the runner cannot run is refused", "no exception")

                # The constraint itself, not just the application logic: this
                # inserts a duplicate triple directly, bypassing the route.
                session.add(SavedCode(user_id=uid, problem_id=1, language="python", code="dup"))
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    check(
                        True,
                        "the database itself rejects a duplicate (user, problem, language)",
                        "uq_saved_code_user_problem_language held",
                    )
                else:
                    check(
                        False,
                        "the database itself rejects a duplicate (user, problem, language)",
                        "a duplicate row was accepted - the old constraint is still in place",
                    )
            finally:
                # Cascade removes the drafts, so nothing is left behind even if
                # an assertion above raised.
                session.rollback()
                session.delete(session.get(User, uid))
                session.commit()
                remaining = session.scalar(
                    sa_select(sa_func.count()).select_from(SavedCode).where(SavedCode.user_id == uid)
                )
                check(
                    remaining == 0,
                    "the throwaway user's drafts are cleaned up",
                    f"{remaining} row(s) left",
                )

    print("\n=== 14. The demo path through the real HTTP route ===")
    # Everything above reaches the runner through `run_submission`, or reaches a
    # route by calling its function directly. Neither proves what the browser
    # actually does: a POST to `/api/submissions/run` that FastAPI parses,
    # authorises, dispatches, executes and then serialises. A field renamed on
    # one side of that boundary is a 500 the student sees, and *no check above
    # would notice* - the runner itself would be perfectly correct.
    #
    # Driving the real ASGI app closes that gap. The only dependency overridden
    # is `current_user`, the one thing a test cannot satisfy without a Clerk
    # token; the override resolves a throwaway user through its own session,
    # exactly the way the real dependency does.
    if not database_ok:
        record(
            SKIP,
            "problem 1 through the real route scores exactly 3/4",
            f"no database: {database_error}",
        )
    else:
        route_marker = f"check-route-{int(time.time())}"
        with db.SessionLocal() as session:
            route_user = User(clerk_user_id=route_marker)
            session.add(route_user)
            session.commit()
            session.refresh(route_user)
            route_uid = route_user.id

        def _as_route_user() -> User:
            """Stand in for ``current_user``, using a session of its own.

            The real dependency resolves the row per request the same way, so
            this is faithful rather than a shortcut.
            """
            with db.SessionLocal() as session:
                return session.scalar(
                    sa_select(User).where(User.clerk_user_id == route_marker)
                )

        # `raise_server_exceptions=False` on purpose: a 500 should come back as
        # a recorded failure with its body, not as a traceback that aborts the
        # whole suite.
        client = TestClient(fastapi_app, raise_server_exceptions=False)
        try:
            # Prove the gate is real before opening it, or this section could
            # quietly become an unauthenticated test that passes against a
            # broken `current_user`.
            anonymous = client.post(
                "/api/submissions/run",
                json={"problem_id": 1, "language": "python", "code": NAIVE},
            )
            expected_anonymous = 401 if config.auth_configured() else 503
            check(
                anonymous.status_code == expected_anonymous,
                "and the route really is gated, not merely overridden",
                f"HTTP {anonymous.status_code} with no session "
                f"(expected {expected_anonymous})",
            )

            fastapi_app.dependency_overrides[current_user] = _as_route_user

            for language, source in (("python", NAIVE), ("javascript", NAIVE_JS)):
                response = client.post(
                    "/api/submissions/run",
                    json={"problem_id": 1, "language": language, "code": source},
                )
                if response.status_code != 200:
                    record(
                        FAIL,
                        f"problem 1 through the real route scores exactly 3/4 in {language}",
                        f"HTTP {response.status_code}: {response.text[:200]}",
                    )
                    continue

                body = response.json()
                # `partial`, not `failed`. `_determine_status` reserves `failed`
                # for a run where nothing at all passed; three of four passing is
                # exactly the demo's headline number, and the UI colours it amber
                # rather than red. Asserting `failed` here was wrong the first
                # time this ran - which is the check doing its job.
                check(
                    body["passed"] == 3 and body["total"] == 4 and body["status"] == "partial",
                    f"problem 1 through the real route scores exactly 3/4 in {language}",
                    f"{body['passed']}/{body['total']} status={body['status']}",
                )

                failed = [t for t in body["tests"] if not t["passed"]]
                check(
                    len(failed) == 1 and failed[0]["name"] == "Large input (performance)",
                    f"and the performance case is the one that fails, in {language}",
                    f"failed: {[t['name'] for t in failed]}",
                )
                if failed:
                    perf = failed[0]
                    mechanism = (
                        f"error_type={perf['error_type']} "
                        f"elapsed={float(perf['elapsed'] or 0):.4f}s"
                    )
                    timed_out = perf["error_type"] == "timeout"
                else:
                    mechanism = "no case failed - the naive solution passed everywhere"
                    timed_out = False
                check(
                    timed_out,
                    f"by the same mechanism the CLI reports, in {language}",
                    mechanism,
                )
                check(
                    isinstance(body.get("submission_id"), int),
                    f"and the run was recorded, so a review can attach to it, in {language}",
                    f"submission_id={body.get('submission_id')}",
                )
                check(
                    set(body["tests"][0])
                    >= {"name", "passed", "error_type", "elapsed", "compute", "stdout"},
                    f"the JSON the browser receives carries what the UI reads, in {language}",
                    f"{len(body['tests'][0])} fields per case",
                )
        finally:
            fastapi_app.dependency_overrides.clear()
            with db.SessionLocal() as session:
                for row in session.scalars(
                    sa_select(Submission).where(Submission.user_id == route_uid)
                ):
                    session.delete(row)
                session.delete(session.get(User, route_uid))
                session.commit()
                left = session.scalar(
                    sa_select(sa_func.count())
                    .select_from(Submission)
                    .where(Submission.user_id == route_uid)
                )
                check(
                    left == 0,
                    "the throwaway user's runs are cleaned up",
                    f"{left} row(s) left",
                )

    print("\n=== 15. Measured complexity has an input to scale (phase 5) ===")
    # Phase 5 measures growth by running a submission at two or more input
    # sizes. Until this section existed, exactly **one** of the twelve problems
    # declared a `generate` case, so a ladder could be built for Contains
    # Duplicate and nothing else - and the other eleven would have reported
    # "not measured" while looking perfectly healthy. The dangerous version of
    # this bug is silent, so it is asserted rather than eyeballed.
    #
    # What this section does NOT do is assert a *classification*. Turning a
    # ladder into "this is O(n^2)" is phase 5's own job, and the plan already
    # records why that is delicate: problem 1's optimal hash-set solution reads
    # 2.54-3.15x per doubling against an ideal 2.0x, so a fixed threshold would
    # call a correct answer quadratic. Here we prove the instrument works; the
    # verdict gets its own tests.
    catalogue = problem_data.list_problems()

    unscalable = [p["id"] for p in catalogue if problem_data.scaling_spec(p) is None]
    check(
        not unscalable,
        "every problem declares how to build an input of size n",
        f"{len(catalogue) - len(unscalable)}/{len(catalogue)} scalable"
        + (f", missing: {unscalable}" if unscalable else ""),
    )

    scaling_faults = [f for f in problem_data.validate_catalogue() if "scaling" in f]
    check(
        not scaling_faults,
        "and every spec names a kind that exists and actually builds an input",
        "; ".join(scaling_faults)[:220]
        if scaling_faults
        else f"{len(scaling.SCALING_KINDS)} kinds defined",
    )

    # The input has to grow with n, or the ladder measures the same work three
    # times and calls it flat. Checked on the serialised payload, which is also
    # what actually crosses into the container.
    import json as _json  # noqa: PLC0415 - only needed for this measurement

    flat, arity_wrong = [], []
    for problem in catalogue:
        spec = problem_data.scaling_spec(problem)
        if spec is None:
            continue
        small = scaling.resolve_scaling_args(spec, 500)
        large = scaling.resolve_scaling_args(spec, 2000)
        if len(_json.dumps(large)) <= len(_json.dumps(small)):
            flat.append(problem["id"])
        declared = len(problem["languages"]["python"]["params"])
        if len(small) != declared:
            arity_wrong.append(f"#{problem['id']} builds {len(small)} args, signature has {declared}")
    check(
        not flat,
        "the generated input really grows with n, for every problem",
        f"payload grows for {len(catalogue) - len(flat)}/{len(catalogue)}"
        + (f", flat: {flat}" if flat else ""),
    )
    check(
        not arity_wrong,
        "and each spec builds exactly the arguments the signature declares",
        "; ".join(arity_wrong)[:220] if arity_wrong else f"{len(catalogue)} signatures matched",
    )

    # How the measurement inputs are built is the reviewer's business, not the
    # client's. `to_public` names its fields explicitly, so this asserts that
    # `scaling` was not quietly added to either projection.
    leaked = [
        p["id"] for p in catalogue if "scaling" in problem_data.to_public(p, include_languages=True)
    ]
    check(
        not leaked,
        "the scaling spec never reaches the API",
        f"clean across {len(catalogue)} problems" if not leaked else f"leaked on {leaked}",
    )

    # The load-bearing check: every generated input must be one the problem's
    # own reference solution accepts. A spec can name a real kind and still
    # build something the signature cannot take - a flat list where the problem
    # wants pairs of pairs, say - and nothing above would notice.
    #
    # n=200 on purpose: the input is tiny so the cost is container lifecycle
    # rather than student code, and what is being proved is acceptance, not
    # speed. One container per problem.
    refused = []
    for problem in catalogue:
        solution = REFERENCE.get(problem["id"])
        if not solution:
            continue
        measurement = code_runner.measure_scaling(
            problem, solution, "python", sizes=(200,), reps=1
        )
        if not measurement.ok:
            refused.append(f"#{problem['id']}: {measurement.message}")
    check(
        not refused,
        "every problem's reference solution runs on its own generated ladder",
        "; ".join(refused)[:240] if refused else f"{len(catalogue)} problems, one ladder each",
    )

    # A missing measurement must be None, never 0.0: a zero reads as an
    # infinitely fast solution, which would classify as constant time - the
    # opposite of the truth for a submission that timed out.
    broken = code_runner.measure_scaling(
        problem_data.get_problem(1), "def containsDuplicate(nums)\n    return False\n", "python",
        sizes=(500,), reps=1,
    )
    check(
        not broken.ok and all(value is None for value in broken.compute),
        "a submission that cannot run reports no measurement rather than zero",
        f"ok={broken.ok} compute={broken.compute} message={broken.message}",
    )

    try:
        code_runner.measure_scaling(problem_data.get_problem(1), "x", "cobol")
    except UnsupportedLanguage as exc:
        check(True, "measuring refuses an unsupported language, like running does", str(exc)[:90])
    except Exception as exc:  # noqa: BLE001 - any other type is the failure
        check(False, "measuring refuses an unsupported language, like running does", repr(exc)[:120])
    else:
        check(
            False,
            "measuring refuses an unsupported language, like running does",
            "no exception raised",
        )

    # And the ladder has to carry a usable signal. This is the one check here
    # that asserts something about the *instrument* rather than the data: a
    # quadratic solution must grow visibly faster than a known-linear probe over
    # the same span.
    #
    # The margin is 2x, which is not a tuned constant but half the *ideal*
    # ratio: over a 4x span a quadratic solution grows ~16x against a linear
    # ~4x, so 2x is a 2x safety margin on theory. Measured 2026-09-23 the
    # separation was 15.8x vs 4.0x in Python and 15.0x vs 5.0x in JavaScript,
    # with the probe reading near-ideal at 4.0x and 5.0x against the predicted
    # 4x - so the margin is not close to binding.
    #
    # An incomplete ladder is **skipped, not failed**: a machine that cannot
    # finish one has an environment fault, which is exactly what happened on
    # 2026-09-23 when C: was full and Docker returned `exit 125` on container
    # creation. The same run's other sections failed for that reason too.
    demo = problem_data.get_problem(1)
    ladder = {
        ("python", "naive"): code_runner.measure_scaling(
            demo, NAIVE, "python", sizes=SIGNAL_SIZES, reps=1
        ),
        ("python", "linear"): code_runner.measure_scaling(
            demo, LINEAR_PROBE, "python", sizes=SIGNAL_SIZES, reps=1
        ),
        ("javascript", "naive"): code_runner.measure_scaling(
            demo, NAIVE_JS, "javascript", sizes=SIGNAL_SIZES, reps=1
        ),
        ("javascript", "linear"): code_runner.measure_scaling(
            demo, LINEAR_PROBE_JS, "javascript", sizes=SIGNAL_SIZES, reps=1
        ),
    }

    def growth(measurement) -> float | None:
        """How much slower the largest size was than the smallest."""
        if not measurement.ok:
            return None
        first, last = measurement.compute[0], measurement.compute[-1]
        if not first or last is None:
            return None
        return last / first

    # `ladder` is keyed by tuples, so the failing keys must stay tuples until
    # they are formatted. This line previously built the list as strings and
    # then indexed `ladder` with them, which raised KeyError - meaning the
    # *skip* path, written for exactly the loaded-machine case it was hit by,
    # crashed the suite instead of reporting. Never exercised until 2026-09-23.
    incomplete = [key for key, measurement in ladder.items() if not measurement.ok]
    if incomplete:
        labels = ", ".join(f"{lang}/{kind}" for lang, kind in incomplete)
        reasons = "; ".join(
            f"{lang}/{kind}: {ladder[(lang, kind)].message}" for lang, kind in incomplete
        )
        record(
            SKIP,
            "the ladder separates a quadratic solution from a linear probe",
            f"ladder did not complete ({labels}) - {reasons[:160]}",
        )
    else:
        for language in ("python", "javascript"):
            naive_growth = growth(ladder[(language, "naive")])
            linear_growth = growth(ladder[(language, "linear")])
            assert naive_growth is not None and linear_growth is not None
            check(
                naive_growth > 2 * linear_growth,
                f"the ladder separates quadratic from linear in {language}",
                f"naive grew {naive_growth:.1f}x vs a linear probe's {linear_growth:.1f}x "
                f"over n={SIGNAL_SIZES[0]}->{SIGNAL_SIZES[1]}",
            )

    print("\n" + "=" * 66)
    counts = {s: sum(1 for r in results if r[0] == s) for s in (PASS, FAIL, SKIP)}
    print(f"  {counts[PASS]} passed   {counts[FAIL]} failed   {counts[SKIP]} skipped")
    print("=" * 66)
    for status, name, detail in results:
        if status != PASS:
            print(f"  [{status}] {name}: {detail}")

    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
