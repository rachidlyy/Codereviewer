"""How to build an input of size *n* for a problem, so growth can be measured.

Deliberately separate from ``test_cases.py``. A test case states one specific
input *and the answer it should produce*; a scaling spec states only the
**shape** of an input of size ``n`` and carries no expected value at all,
because a measurement only needs the student's code to run - it never looks at
what came back. Folding the two together would make "no expected value" look
like a malformed test case and would invite someone to "fix" it.

Why this exists
---------------
Measured complexity needs the student's own code timed at two or more input
sizes. Until this module, exactly **one** of the twelve problems declared a
``generate`` case, so a ladder could be built for Contains Duplicate and
nothing else - and every other problem would have silently reported "not
measured" while looking perfectly healthy.

What ``n`` means
----------------
``n`` is the size of the **primary** input, not a count of every value in the
call. For a list problem it is the list length; for a string problem, the
string length; for Merge Intervals, the number of intervals; for Median of Two
Sorted Arrays, the total across both arrays. Each kind documents its own
reading, and ``check_runner`` asserts the payload actually grows with ``n``
rather than trusting that.

What the inputs are chosen for
------------------------------
Not for correctness - nothing is checked - but so that a solution does its
**typical** work rather than bailing out early. Two Sum's target is reachable
only from the last two elements, so a quadratic scan cannot find it on the
first pass and measure as if it were constant. Valid Parentheses gets a
balanced string, so a stack solution consumes all of it. Valid Anagram gets two
strings that *are* anagrams, so a length-mismatch early return does not
collapse the measurement to nothing.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

#: Ladder used when the caller does not supply one.
#:
#: Chosen from the measured ladder in ``check_runner`` section 5b. Small enough
#: that a quadratic solution's whole ladder costs a couple of seconds rather
#: than tens, large enough to clear the noise floor: below a few thousand
#: elements a linear solution finishes in under a millisecond, and the plan
#: already records that a sub-millisecond measurement reads as noise (pairwise
#: ratios for a genuinely linear solution came out 2.63, 1.64, 2.74, 1.31).
#:
#: **This is not the performance case's size.** The naive solution needs 10.48s
#: at n=200,000, which is right for a deliberate timeout demo and hopeless for a
#: ladder that runs on every review.
DEFAULT_SIZES: tuple[int, ...] = (4_000, 16_000, 64_000)

#: Best-of-N rather than the mean, because the noise here is one-sided: a
#: measurement is only ever slowed down by the machine, never sped up.
DEFAULT_REPS: int = 2


class ScalingSpec(TypedDict, total=False):
    """A problem's entry in ``problems.json`` under ``scaling``."""

    kind: str


class BadScaling(ValueError):
    """A scaling spec that cannot be turned into arguments."""


def _int_list(n: int) -> list[Any]:
    """One list of ``n`` distinct integers - ``n`` is the list length.

    Distinct on purpose: a duplicate-free input makes a hash-set solution do
    its full ``n`` insertions instead of returning on the first collision.
    """
    return [list(range(n))]


def _unit_int_list(n: int) -> list[Any]:
    """One list of ``n`` ones.

    Product of Array Except Self. Every element is **1** so the running prefix
    and suffix products stay inside a machine word. With values of 2 or more the
    products grow to ``n`` bits, and multiplying them is ``O(n^2)`` in *bit*
    operations even for the intended linear solution - a false quadratic signal
    produced entirely by big-integer arithmetic rather than by the algorithm.
    A degenerate input, but an honest one: it measures the loop structure, which
    is the only thing this ladder is for.
    """
    return [[1] * n]


def _int_list_with_target(n: int) -> list[Any]:
    """A list of ``n`` integers plus a target only the last two reach.

    Two Sum. ``target = (n-2) + (n-1)`` is the largest possible pair sum, so a
    quadratic double loop has to scan to the very end before it finds anything.
    A target reachable early - the obvious ``n // 2`` - would let the naive
    solution return on its first pass and measure as if it were O(1).
    """
    nums = list(range(n))
    target = (n - 2) + (n - 1) if n >= 2 else 0
    return [nums, target]


def _sorted_int_list_with_target(n: int) -> list[Any]:
    """A sorted list of ``n`` integers and a target that is present.

    Binary Search. ``range(n)`` is already sorted and the midpoint value is in
    the list, so a correct binary search takes ``log n`` steps while a linear
    scan takes ``n`` - which is exactly the pair this problem exists to tell
    apart.
    """
    nums = list(range(n))
    return [nums, nums[n // 2] if nums else 0]


def _str_pair(n: int) -> list[Any]:
    """Two strings of length ``n`` that **are** anagrams of each other.

    Valid Anagram. They are anagrams so that a correct solution cannot return
    early on a length or character-count mismatch - it has to do the whole
    comparison. The alphabet is small and repeating, which keeps the payload
    compact while still forcing ``n`` characters through the count.
    """
    text = ("abcdefghij" * (n // 10 + 1))[:n]
    return [text, text[::-1]]


def _brackets(n: int) -> list[Any]:
    """A **balanced** bracket string of length ``n``.

    Valid Parentheses. Balanced, so a stack solution walks the entire string
    and returns True. An unbalanced string would let it stop at the first
    mismatch and measure the prefix rather than ``n``.
    """
    return ["()" * (n // 2)]


def _word_list(n: int) -> list[Any]:
    """``n`` short, distinct words - ``n`` is the number of words.

    Group Anagrams. Kept to four characters each so the cost is dominated by
    the *number* of words, which is what ``n`` means here, rather than by
    sorting each word. Distinct so no two words collapse into one group and
    shorten the work.
    """
    return [[f"w{i % 997:03d}{'abcdefghij'[i % 10]}" for i in range(n)]]


def _intervals(n: int) -> list[Any]:
    """``n`` sorted, non-overlapping intervals - ``n`` is the interval count.

    Merge Intervals. Already sorted and disjoint, so an ``O(n log n)`` merge
    does its full work and nothing merges unexpectedly into a shorter result.
    """
    return [[[2 * i, 2 * i + 1] for i in range(n)]]


def _letters(n: int) -> list[Any]:
    """A string of length ``n`` drawn from a repeating 10-letter alphabet.

    Longest Substring Without Repeating Characters. The repetition keeps the
    payload small while still forcing the sliding window across all ``n``
    characters - an all-distinct string would need ``n`` distinct characters
    and a much larger payload for the same amount of work.
    """
    return [("abcdefghij" * (n // 10 + 1))[:n]]


def _two_int_lists(n: int) -> list[Any]:
    """Two **sorted** integer lists totalling ``n`` elements.

    Median of Two Sorted Arrays. Interleaved evens and odds, so both halves are
    sorted, the merge is the worst case, and a naive merge costs ``n`` while the
    intended partition walk costs ``log n``.
    """
    half = max(n // 2, 1)
    return [list(range(0, 2 * half, 2)), list(range(1, 2 * half, 2))]


#: Every kind a ``scaling`` spec may name. Adding a problem with a new input
#: shape means adding a kind here and naming it in ``problems.json`` - the two
#: are checked against each other by ``validate_scaling_spec``.
SCALING_KINDS: dict[str, Callable[[int], list[Any]]] = {
    "int_list": _int_list,
    "unit_int_list": _unit_int_list,
    "int_list_with_target": _int_list_with_target,
    "sorted_int_list_with_target": _sorted_int_list_with_target,
    "str_pair": _str_pair,
    "brackets": _brackets,
    "word_list": _word_list,
    "intervals": _intervals,
    "letters": _letters,
    "two_int_lists": _two_int_lists,
}


def resolve_scaling_args(spec: ScalingSpec | None, n: int) -> list[Any]:
    """Expand a scaling spec into the positional arguments for size ``n``.

    Raises :class:`BadScaling` rather than returning a short list, so a typo in
    the catalogue is a loud failure at the point of use instead of a ladder of
    empty inputs that measures nothing and reports success.
    """
    if not spec:
        raise BadScaling("The problem declares no 'scaling' spec.")

    kind = spec.get("kind")
    if not kind:
        raise BadScaling("The 'scaling' spec names no 'kind'.")

    builder = SCALING_KINDS.get(kind)
    if builder is None:
        known = ", ".join(sorted(SCALING_KINDS))
        raise BadScaling(f"Unknown scaling kind {kind!r}. Known kinds: {known}.")

    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise BadScaling(f"A scaling size must be a positive integer, got {n!r}.")

    return builder(n)


def validate_scaling_spec(spec: ScalingSpec | None) -> str | None:
    """Return a human-readable fault, or None when the spec is usable.

    Checks the kind *and* actually builds a small input, because a spec can name
    a real kind and still blow up - and the failure would otherwise surface
    mid-review rather than at validation time.
    """
    if not spec:
        return "no 'scaling' spec, so no measured complexity is possible"
    kind = spec.get("kind")
    if kind not in SCALING_KINDS:
        known = ", ".join(sorted(SCALING_KINDS))
        return f"unknown scaling kind {kind!r} (known: {known})"
    try:
        args = resolve_scaling_args(spec, 64)
    except BadScaling as exc:  # pragma: no cover - guarded by the kind check above
        return str(exc)
    if not args:
        return "the scaling spec produces no arguments"
    return None
