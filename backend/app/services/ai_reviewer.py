"""AI code review service.

All LLM logic lives here - routes never talk to a model provider directly
(plan section 11). The provider is reached over plain REST via ``httpx``
so that swapping Gemini for OpenAI, or a self-hosted model, means editing
only the ``_call_llm`` function in this file.

Two modes
---------
* **LLM mode** - ``GEMINI_API_KEY`` is set. The submission is sent to
  Gemini and the response is validated against :class:`ReviewResponse`.
  If the call fails, :class:`ReviewUnavailable` is raised and the route
  turns it into a 503 so the UI can show the "temporarily unavailable"
  message from plan section 16. A failed LLM call never crashes the page.
* **Offline mode** - no key configured. A deterministic rule-based
  reviewer produces a structured review so the whole workflow can still be
  demonstrated. Results are tagged ``source="heuristic"`` so the UI can be
  honest about it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app import config
from app.data.problems import Problem
from app.schemas.submission import ReviewResponse

logger = logging.getLogger(__name__)


class ReviewUnavailable(RuntimeError):
    """Raised when the configured LLM could not produce a review.

    ``retry_after`` carries the provider's own estimate of how long to wait
    when it gave one, so the route can tell the student something more useful
    than "try again" when the failure is a rate limit rather than a blip.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
You are CodeReviewer, an expert code reviewer and programming mentor on a \
university coding-practice platform.

Review the student's submitted solution to the problem below. You are a \
mentor, NOT a code generator: do not simply hand over the optimal answer.

PROBLEM
Title: {title}
Difficulty: {difficulty}
Category: {category}
Description: {description}

STUDENT CODE
{code}

AUTOMATED TEST RESULTS
{passed} of {total} test cases passed.
Overall status: {status}
{test_detail}
Total execution time: {execution_time}s

REVIEW RULES
1. Base every statement on the student's actual code and the actual test \
results above.
2. Never invent test results, and never claim the code is correct if the \
test results indicate otherwise.
3. If the code is correct but inefficient, say so explicitly, name the \
complexity, and explain why it matters as input grows.
4. If tests failed, identify the most likely cause by reading the code.
5. Refer to the student's actual constructs (for example "your nested for \
loops") instead of giving generic advice.
6. The hint must nudge the student toward the fix without revealing the \
full solution. Put the fuller strategy in improved_approach, which the UI \
keeps hidden behind a button.
7. Scores are out of 10. overall_score should reflect the weighted picture, \
not just correctness.
8. Tone: supportive, precise, educational. No emoji, no markdown headings \
inside string values, no code blocks.

Return ONLY one JSON object with exactly these keys:
{{
  "overall_score": number,
  "correctness_score": number,
  "readability_score": number,
  "efficiency_score": number,
  "summary": string,
  "issues": [{{"type": "correctness" | "efficiency" | "readability", "title": string, "explanation": string}}],
  "suggestions": [string],
  "complexity": {{"current_time": string, "current_space": string, "suggested_time": string, "suggested_space": string}},
  "hint": string,
  "improved_approach": string
}}
"""


def build_prompt(problem: Problem, code: str, test_result: dict[str, Any]) -> str:
    """Assemble the mentor prompt from problem, code and execution results."""
    failed_tests = test_result.get("failed_tests") or []
    if failed_tests:
        test_detail = "Failing test cases: " + ", ".join(failed_tests) + "."
    elif test_result.get("total"):
        test_detail = "All test cases passed."
    else:
        test_detail = "No test results were supplied."

    return PROMPT_TEMPLATE.format(
        title=problem["title"],
        difficulty=problem["difficulty"],
        category=problem["category"],
        description=problem["description"],
        code=code.strip() or "# (empty submission)",
        passed=test_result.get("passed", 0),
        total=test_result.get("total", 0),
        status=test_result.get("status") or "unknown",
        test_detail=test_detail,
        execution_time=test_result.get("execution_time", 0.0),
    )


# --------------------------------------------------------------------------
# LLM transport (the only provider-specific code in the app)
# --------------------------------------------------------------------------


def _extract_text(data: dict[str, Any]) -> str:
    """Pull the text out of a Gemini generateContent response."""
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = (data.get("promptFeedback") or {}).get("blockReason")
        raise ReviewUnavailable(
            f"Gemini returned no candidates{f' (blocked: {feedback})' if feedback else ''}."
        )
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        finish = candidates[0].get("finishReason")
        raise ReviewUnavailable(f"Gemini returned an empty response (finishReason: {finish}).")
    return text


#: HTTP statuses worth retrying. Google returns 503 "high demand" and 429
#: for transient capacity/rate conditions.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Upper bound on a single exponential-backoff sleep, so retries stay bounded.
MAX_RETRY_DELAY_SECONDS = 10.0

#: Cap on how much of a provider error message is kept in an exception.
#:
#: Generous on purpose: Google's quota message puts the actionable part
#: ("limit: 5", "Please retry in 50.7s") at the *end*, after two help URLs,
#: so a tight slice cuts off exactly what you need to diagnose the failure.
MAX_ERROR_MESSAGE_CHARS = 600


def _server_retry_delay(response: httpx.Response | None) -> float | None:
    """Seconds the provider explicitly asked us to wait, if it said so.

    Gemini does **not** send a ``Retry-After`` header on a 429. It puts the
    wait in the body instead::

        {"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
             "retryDelay": "50s"}]}}

    Both are checked, because guessing at a backoff cannot beat being told.
    """
    if response is None:
        return None

    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass

    try:
        details = (response.json().get("error") or {}).get("details") or []
    except ValueError:
        return None

    for detail in details:
        if str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
            raw = str(detail.get("retryDelay", ""))
            if raw.endswith("s"):
                try:
                    return max(0.0, float(raw[:-1]))
                except ValueError:
                    return None
    return None


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff for transient failures that stated no wait."""
    return min(config.LLM_RETRY_BACKOFF_SECONDS * (2**attempt), MAX_RETRY_DELAY_SECONDS)


def _describe_http_error(response: httpx.Response) -> str:
    """A one-line reason for a failed call, without a mid-sentence cut.

    The provider's ``error.message`` is the useful part - it names the quota
    and how long to wait. Blindly slicing the raw body truncates exactly that.
    """
    message = ""
    try:
        message = (response.json().get("error") or {}).get("message") or ""
    except ValueError:
        message = ""
    message = " ".join(str(message).split()) or " ".join(response.text.split())
    if len(message) > MAX_ERROR_MESSAGE_CHARS:
        message = message[: MAX_ERROR_MESSAGE_CHARS - 3] + "..."
    return f"Gemini returned HTTP {response.status_code}: {message}"


async def _call_llm(prompt: str) -> str:
    """Send the prompt to Gemini, retrying transient failures.

    Google's flash models intermittently answer with HTTP 503 "currently
    experiencing high demand", and the free tier allows only a handful of
    requests per minute before returning 429. Those are transient capacity
    conditions, not configuration problems, so they are retried rather than
    surfaced to the student - see ``config.LLM_MAX_ATTEMPTS``.

    A 429 is different from a 503: the per-minute quota does not clear in a
    second or two, so the wait the provider asks for is honoured when it is
    short, and the call fails fast when it is not.
    """
    url = f"{config.GEMINI_API_URL}/models/{config.GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": config.LLM_TEMPERATURE,
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "x-goog-api-key": config.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    attempts = max(1, config.LLM_MAX_ATTEMPTS)
    last_reason = "unknown error"

    for attempt in range(attempts):
        is_last = attempt + 1 >= attempts
        response: httpx.Response | None = None
        delay = _backoff_delay(attempt)

        try:
            async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            last_reason = f"no response within {config.LLM_TIMEOUT_SECONDS:g}s"
            if is_last:
                raise ReviewUnavailable(
                    f"The model did not respond within {config.LLM_TIMEOUT_SECONDS:g}s."
                ) from exc
            logger.warning("Gemini timed out (attempt %d/%d), retrying.", attempt + 1, attempts)
        except httpx.HTTPError as exc:
            last_reason = f"could not reach the provider ({exc})"
            if is_last:
                raise ReviewUnavailable(f"Could not reach the model provider: {exc}") from exc
            logger.warning(
                "Gemini unreachable (attempt %d/%d), retrying.", attempt + 1, attempts
            )
        else:
            if response.status_code < 400:
                try:
                    return _extract_text(response.json())
                except ValueError as exc:
                    raise ReviewUnavailable(
                        "Gemini returned a malformed response body."
                    ) from exc

            last_reason = _describe_http_error(response)

            if response.status_code not in RETRYABLE_STATUSES:
                # A real error - retrying will not help.
                raise ReviewUnavailable(last_reason)

            if is_last:
                break

            advised = _server_retry_delay(response)

            if advised is not None and advised > config.LLM_MAX_RETRY_WAIT_SECONDS:
                # Holding the request open for this long is worse for the
                # student than an honest failure, and the remaining attempts
                # would be spent against a quota that has not reset yet.
                logger.warning(
                    "Gemini asked for a %.0fs wait (attempt %d/%d) - failing fast "
                    "instead of holding the request open.",
                    advised,
                    attempt + 1,
                    attempts,
                )
                raise ReviewUnavailable(
                    f"{last_reason} The provider asked for a {advised:.0f}s wait.",
                    retry_after=advised,
                )

            if advised is not None:
                delay = advised

            logger.warning(
                "Gemini transient failure HTTP %s (attempt %d/%d), retrying in %.1fs.",
                response.status_code,
                attempt + 1,
                attempts,
                delay,
            )

        await asyncio.sleep(delay)

    raise ReviewUnavailable(f"Gemini was unavailable after {attempts} attempts ({last_reason}).")


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_review_json(raw: str) -> dict[str, Any]:
    """Parse the model's reply into a dict, tolerating common wrappers."""
    text = _FENCE_RE.sub("", raw.strip())

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost JSON object in the text.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ReviewUnavailable(f"The model did not return valid JSON: {exc}") from exc

    raise ReviewUnavailable("The model did not return valid JSON.")


def _coerce_score(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return round(max(0.0, min(10.0, score)), 1)


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value).strip() or default


def normalise_review(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Coerce a raw review dict into the exact shape the API promises.

    LLM output is never trusted to be perfectly shaped; every field is
    defaulted and clamped so the frontend can render unconditionally.
    """
    raw_issues = data.get("issues") or []
    issues = []
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue
            title = _coerce_str(issue.get("title"))
            explanation = _coerce_str(issue.get("explanation"))
            if not title and not explanation:
                continue
            issues.append(
                {
                    "type": _coerce_str(issue.get("type"), "general").lower(),
                    "title": title or "Issue",
                    "explanation": explanation,
                }
            )

    raw_suggestions = data.get("suggestions") or []
    suggestions = []
    if isinstance(raw_suggestions, list):
        suggestions = [text for text in (_coerce_str(s) for s in raw_suggestions) if text]
    elif isinstance(raw_suggestions, str):
        suggestions = [_coerce_str(raw_suggestions)]

    raw_complexity = data.get("complexity") or {}
    if not isinstance(raw_complexity, dict):
        raw_complexity = {}

    correctness = _coerce_score(data.get("correctness_score"), 5.0)
    efficiency = _coerce_score(data.get("efficiency_score"), 5.0)
    readability = _coerce_score(data.get("readability_score"), 5.0)
    overall = _coerce_score(
        data.get("overall_score"),
        round(0.5 * correctness + 0.25 * efficiency + 0.25 * readability, 1),
    )

    return {
        "overall_score": overall,
        "correctness_score": correctness,
        "readability_score": readability,
        "efficiency_score": efficiency,
        "summary": _coerce_str(data.get("summary"), "No summary was produced."),
        "issues": issues,
        "suggestions": suggestions,
        "complexity": {
            "current_time": _coerce_str(raw_complexity.get("current_time"), "—"),
            "current_space": _coerce_str(raw_complexity.get("current_space"), "—"),
            "suggested_time": _coerce_str(raw_complexity.get("suggested_time"), "—"),
            "suggested_space": _coerce_str(raw_complexity.get("suggested_space"), "—"),
        },
        "hint": _coerce_str(data.get("hint")),
        "improved_approach": _coerce_str(data.get("improved_approach")),
        "source": source,
    }


# --------------------------------------------------------------------------
# Offline reviewer (used when no API key is configured)
# --------------------------------------------------------------------------

#: Per-problem guidance so the offline reviewer can still say something
#: specific rather than generic. Keyed by problem id.
_PROBLEM_GUIDANCE: dict[int, dict[str, str]] = {
    1: {
        "naive_time": "O(n²)",
        "naive_space": "O(1)",
        "good_time": "O(n)",
        "good_space": "O(n)",
        "hint": (
            "Think about a data structure that can tell you whether a value has "
            "already appeared in constant time. What happens if you record each "
            "value as you walk through the array once?"
        ),
        "approach": (
            "Walk the array a single time while adding each value to a hash set. "
            "Before inserting, check whether the set already contains it - if so, "
            "return True immediately. If the loop finishes, every value was "
            "distinct, so return False. This trades O(n) extra space for linear time."
        ),
        "issue_title": "Nested loops cause quadratic runtime",
        "issue_body": (
            "Your solution compares every pair of elements, which performs on the "
            "order of n² comparisons. That is fine for the small examples, but on "
            "the 20,000-element test case the comparison count explodes, which is "
            "why that test case timed out."
        ),
    },
    2: {
        "naive_time": "O(n²)",
        "naive_space": "O(1)",
        "good_time": "O(n)",
        "good_space": "O(n)",
        "hint": (
            "For each number you look at, you know exactly what its partner must "
            "be. Can you remember the values you have already passed so you can "
            "look that partner up instantly?"
        ),
        "approach": (
            "Keep a dictionary mapping each value to its index. For every element, "
            "compute the complement (target minus the current value) and check "
            "whether it is already in the dictionary. If it is, you have found the "
            "pair; otherwise store the current value and continue."
        ),
        "issue_title": "Nested loops cause quadratic runtime",
        "issue_body": (
            "Checking every pair of numbers means roughly n² additions. A single "
            "pass with a lookup table gives the same answer in linear time."
        ),
    },
    3: {
        "naive_time": "O(n log n)",
        "naive_space": "O(n)",
        "good_time": "O(n)",
        "good_space": "O(n)",
        "hint": (
            "Two strings are anagrams when they use exactly the same characters "
            "the same number of times. Is there a way to compare those counts "
            "without reordering either string?"
        ),
        "approach": (
            "Count the characters of one string in a dictionary (or "
            "collections.Counter) and decrement those counts while walking the "
            "other string. If every count returns to zero, the strings are "
            "anagrams. An early length check makes mismatched inputs fail instantly."
        ),
        "issue_title": "Sorting is more work than counting",
        "issue_body": (
            "Sorting both strings costs O(n log n) and allocates two new lists. "
            "Comparing character counts directly does the same job in a single "
            "linear pass."
        ),
    },
    4: {
        "naive_time": "O(n)",
        "naive_space": "O(1)",
        "good_time": "O(log n)",
        "good_space": "O(1)",
        "hint": (
            "The array is already sorted. Each comparison you make can rule out "
            "half of the remaining elements - are you taking advantage of that?"
        ),
        "approach": (
            "Track a low and high boundary and repeatedly inspect the middle "
            "element. Depending on whether it is below or above the target, discard "
            "the half that cannot contain it. The search space halves every step, "
            "giving logarithmic time."
        ),
        "issue_title": "Linear scan ignores the sorted order",
        "issue_body": (
            "Scanning from the left checks up to n elements. Because the input is "
            "sorted, a binary search needs only about log₂(n) comparisons."
        ),
    },
    5: {
        "naive_time": "O(n²)",
        "naive_space": "O(1)",
        "good_time": "O(n)",
        "good_space": "O(1)",
        "hint": (
            "As you move through the array, is a negative running sum ever worth "
            "keeping? What is the best subarray ending at the current position?"
        ),
        "approach": (
            "Kadane's algorithm tracks the best sum ending at the current index. "
            "At each element you either extend the previous subarray or start fresh "
            "from the current element, whichever is larger, and record the best "
            "value seen so far. One pass, constant extra space."
        ),
        "issue_title": "Recomputing every subarray is quadratic",
        "issue_body": (
            "Trying every start and end index recomputes overlapping sums, which "
            "grows with n². Carrying a running best forward solves it in one pass."
        ),
    },
}

_GENERIC_GUIDANCE = {
    "naive_time": "O(n²)",
    "naive_space": "O(1)",
    "good_time": "O(n)",
    "good_space": "O(n)",
    "hint": "Look for repeated work in your solution - is there a value you compute more than once that could be remembered instead?",
    "approach": "Identify the repeated work and store intermediate results in a dictionary or set so each element is processed once.",
    "issue_title": "Repeated work in the inner loop",
    "issue_body": "The current approach revisits the same work multiple times, which makes the runtime grow faster than necessary.",
}


def _nested_loop_depth(code: str) -> int:
    """Longest chain of loops nested inside one another."""
    indent_stack: list[int] = []
    max_depth = 0
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^(for|while)\b", stripped):
            indent = len(line) - len(line.lstrip())
            while indent_stack and indent_stack[-1] >= indent:
                indent_stack.pop()
            indent_stack.append(indent)
            max_depth = max(max_depth, len(indent_stack))
        elif not stripped.startswith(("elif", "else")):
            indent = len(line) - len(line.lstrip())
            while indent_stack and indent_stack[-1] >= indent:
                indent_stack.pop()
    return max_depth


def _analyse_code(code: str) -> dict[str, Any]:
    """Extract simple structural signals used by the offline reviewer."""
    return {
        "lines": [line for line in code.splitlines() if line.strip()],
        "nested_depth": _nested_loop_depth(code),
        "uses_hash": bool(re.search(r"\b(set|dict|Counter|defaultdict)\s*\(|\{[^}]*\}", code)),
        "uses_sort": bool(re.search(r"\bsorted\s*\(|\.sort\s*\(", code)),
        "has_comment": "#" in code,
        "uses_bisect": "bisect" in code or "// 2" in code or ">> 1" in code,
        "is_placeholder": bool(re.search(r"^\s*pass\s*$", code, re.MULTILINE)) and len(
            [line for line in code.splitlines() if line.strip()]
        ) <= 3,
        "long_lines": sum(1 for line in code.splitlines() if len(line) > 100),
        "single_char_names": len(
            set(re.findall(r"(?<![\w.])([a-z])\s*=", code)) - {"i", "j", "k", "n", "s", "t"}
        ),
    }


def heuristic_review(
    problem: Problem,
    code: str,
    test_result: dict[str, Any],
) -> dict[str, Any]:
    """Rule-based review used when no LLM key is configured."""
    guidance = _PROBLEM_GUIDANCE.get(problem["id"], _GENERIC_GUIDANCE)
    signals = _analyse_code(code)

    total = int(test_result.get("total") or 0)
    passed = int(test_result.get("passed") or 0)
    status = test_result.get("status") or "unknown"
    failed_tests = test_result.get("failed_tests") or []

    # --- correctness ----------------------------------------------------
    if total:
        correctness = round(10.0 * passed / total, 1)
    else:
        correctness = 5.0
    if status == "error" and signals["is_placeholder"]:
        correctness = 0.0

    # --- efficiency -----------------------------------------------------
    efficiency = 9.0
    efficiency_issue: dict[str, str] | None = None

    inefficient = False
    if problem["id"] == 4:
        inefficient = not signals["uses_bisect"] and signals["nested_depth"] == 0
    elif signals["nested_depth"] >= 2:
        inefficient = True
    elif problem["id"] == 3 and signals["uses_sort"] and not signals["uses_hash"]:
        inefficient = True

    if inefficient:
        efficiency = 4.0
        efficiency_issue = {
            "type": "efficiency",
            "title": guidance["issue_title"],
            "explanation": guidance["issue_body"],
        }
        current_time = guidance["naive_time"]
        current_space = guidance["naive_space"]
    else:
        if signals["uses_hash"]:
            efficiency = min(10.0, efficiency + 1.0)
        current_time = guidance["good_time"]
        current_space = guidance["good_space"]

    # --- readability ----------------------------------------------------
    readability = 8.0
    if not signals["has_comment"]:
        readability -= 1.0
    if signals["long_lines"]:
        readability -= 1.0
    if signals["single_char_names"] > 0:
        readability -= 0.5
    if signals["is_placeholder"]:
        readability -= 2.0
    if len(signals["lines"]) > 40:
        readability -= 1.0
    readability = round(max(1.0, min(10.0, readability)), 1)

    # --- summary + issues ----------------------------------------------
    issues: list[dict[str, str]] = []
    if efficiency_issue:
        issues.append(efficiency_issue)

    if failed_tests:
        issues.insert(
            0,
            {
                "type": "correctness",
                "title": "Some test cases did not pass",
                "explanation": (
                    "These test cases failed: "
                    + ", ".join(failed_tests)
                    + ". Compare your logic against the expected output for those inputs."
                ),
            },
        )
        summary = (
            f"Your solution passes {passed} of {total} test cases. "
            + (
                "The approach is sound but not efficient enough for large inputs."
                if efficiency_issue
                else "There is a logic gap on the failing cases to work through."
            )
        )
    elif efficiency_issue:
        summary = (
            f"Your solution passes every test case and is logically correct. "
            f"The main improvement available is performance: the current approach "
            f"runs in {guidance['naive_time']} where {guidance['good_time']} is achievable."
        )
    elif signals["is_placeholder"]:
        summary = "The submission does not contain a solution yet - it still has the starter placeholder."
    else:
        summary = (
            "Your solution passes all test cases and is efficient. "
            "The remaining work is stylistic: naming and comments."
        )

    if not issues and not signals["has_comment"]:
        issues.append(
            {
                "type": "readability",
                "title": "No comments explaining intent",
                "explanation": (
                    "The code has no comments. A short note on why the chosen data "
                    "structure works makes the solution easier to review and reuse."
                ),
            }
        )

    # --- suggestions ----------------------------------------------------
    suggestions: list[str] = []
    if efficiency_issue:
        suggestions.append(guidance["approach"].split(". ")[0] + ".")
    if failed_tests:
        suggestions.append(
            "Add the failing inputs to a scratch run and print the intermediate "
            "values to see where the logic diverges from the expected result."
        )
    if not signals["has_comment"]:
        suggestions.append("Add a one-line comment describing the overall strategy.")
    if not suggestions:
        suggestions.append(
            "Keep this approach. As a next step, consider how it behaves on an "
            "empty input and on very large inputs."
        )

    overall = round(0.5 * correctness + 0.25 * efficiency + 0.25 * readability, 1)

    return normalise_review(
        {
            "overall_score": overall,
            "correctness_score": correctness,
            "readability_score": readability,
            "efficiency_score": efficiency,
            "summary": summary,
            "issues": issues,
            "suggestions": suggestions,
            "complexity": {
                "current_time": current_time,
                "current_space": current_space,
                "suggested_time": guidance["good_time"],
                "suggested_space": guidance["good_space"],
            },
            "hint": guidance["hint"],
            "improved_approach": guidance["approach"],
        },
        source="heuristic",
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def review_submission(
    problem: Problem,
    code: str,
    test_result: dict[str, Any],
) -> dict[str, Any]:
    """Produce a structured review for one submission.

    Raises :class:`ReviewUnavailable` when an LLM is configured but cannot
    be reached - the caller decides how to surface that.
    """
    if not config.llm_enabled():
        return heuristic_review(problem, code, test_result)

    prompt = build_prompt(problem, code, test_result)
    raw = await _call_llm(prompt)
    data = parse_review_json(raw)
    if not isinstance(data, dict):
        raise ReviewUnavailable("The model returned JSON that was not an object.")
    return normalise_review(data, source="gemini")


def validate_review(payload: dict[str, Any]) -> ReviewResponse:
    """Final guard before the response leaves the API."""
    return ReviewResponse.model_validate(payload)
