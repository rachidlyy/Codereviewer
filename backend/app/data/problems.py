"""Problem catalogue, loaded from ``problems.json``.

The catalogue is a plain JSON file rather than a Python literal so that
adding a problem does not mean editing code. The accessors at the bottom of
this module are the only thing the rest of the app touches, so moving the
catalogue into Postgres later means reimplementing them and nothing else.

Every problem carries a ``languages`` map. A language the problem does not
declare is a language it cannot be attempted in, which is what lets the
catalogue grow language by language instead of all at once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from app.data.scaling import ScalingSpec, validate_scaling_spec

PROBLEMS_PATH = Path(__file__).resolve().parent / "problems.json"


class Example(TypedDict):
    input: str
    output: str


class LanguageSpec(TypedDict):
    """How one problem is attempted in one language.

    ``entrypoint`` is the name the harness calls, ``params``/``returns`` are
    the signature the driver generator reads (and the UI shows), and
    ``starter`` seeds the editor.
    """

    entrypoint: str
    params: list[str]
    returns: str
    starter: str


class Problem(TypedDict):
    id: int
    title: str
    difficulty: str
    category: str
    tags: list[str]
    description: str
    examples: list[Example]
    languages: dict[str, LanguageSpec]
    #: How to build an input of size *n*, for measured complexity. Absent on a
    #: problem whose inputs cannot be scaled, which is reported as "not
    #: measured" rather than treated as an error.
    scaling: ScalingSpec


#: Fields returned by the list endpoint. `languages` is held back so the
#: list payload does not carry four starter snippets per problem.
#:
#: `scaling` is held back from **both** projections on purpose: how the
#: measurement inputs are built is an implementation detail of the reviewer,
#: and `to_public` naming its fields explicitly is what keeps it private.
PUBLIC_FIELDS = (
    "id",
    "title",
    "difficulty",
    "category",
    "description",
    "examples",
    "tags",
)

#: Extra fields only the detail endpoint returns, so the coding workspace
#: knows what to seed the editor with and what will be tested.
DETAIL_FIELDS = ("languages",)


def _load() -> list[Problem]:
    with PROBLEMS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


PROBLEMS: list[Problem] = _load()

_BY_ID: dict[int, Problem] = {problem["id"]: problem for problem in PROBLEMS}


def list_problems() -> list[Problem]:
    """Return every problem, in catalogue order."""
    return list(PROBLEMS)


def get_problem(problem_id: int) -> Problem | None:
    """Return a single problem, or None when the id is unknown."""
    return _BY_ID.get(problem_id)


def problem_exists(problem_id: int) -> bool:
    return problem_id in _BY_ID


def languages_for(problem: Problem) -> dict[str, LanguageSpec]:
    """The languages this problem can be attempted in."""
    return problem["languages"]


def supports_language(problem: Problem, language: str) -> bool:
    return language in problem["languages"]


def scaling_spec(problem: Problem) -> ScalingSpec | None:
    """How to build an input of size *n* for this problem, if it can be scaled.

    ``None`` means the problem has no measurable ladder. That is a real state
    rather than an error: a problem whose input cannot be grown honestly cannot
    have its complexity measured, and the reviewer says so instead of guessing.
    """
    spec = problem.get("scaling")
    return spec if isinstance(spec, dict) and spec.get("kind") else None


def to_public(problem: Problem, *, include_languages: bool = False) -> dict[str, Any]:
    """Project a problem record down to the API-safe field set.

    With ``include_languages`` the detail-only field is added on top of the
    list fields. Test cases and expected values are never part of this - the
    client is told what to solve, never how it is checked.
    """
    fields = PUBLIC_FIELDS + (DETAIL_FIELDS if include_languages else ())
    return {field: problem[field] for field in fields}  # type: ignore[literal-required]


def validate_catalogue() -> list[str]:
    """Structural checks over the whole catalogue.

    Returns a list of human-readable problems, empty when the file is sound.
    Not run at import: a broken data file should be reported by the smoke test
    and by pytest rather than crash the API at startup.
    """
    problems: list[str] = []
    seen_ids: set[int] = set()

    for index, problem in enumerate(PROBLEMS):
        where = f"problem {index} ({problem.get('title') or 'untitled'})"

        problem_id = problem.get("id")
        if not isinstance(problem_id, int):
            problems.append(f"{where}: missing or non-integer 'id'")
        elif problem_id in seen_ids:
            problems.append(f"{where}: duplicate id {problem_id}")
        else:
            seen_ids.add(problem_id)

        for field in PUBLIC_FIELDS:
            if not problem.get(field):
                problems.append(f"{where}: missing '{field}'")

        languages = problem.get("languages") or {}
        if not languages:
            problems.append(f"{where}: declares no languages")
        for language, spec in languages.items():
            if not spec.get("entrypoint"):
                problems.append(f"{where}/{language}: missing 'entrypoint'")
            if not spec.get("starter"):
                problems.append(f"{where}/{language}: missing 'starter'")

        # A missing or unusable scaling spec does not break the product - the
        # problem still runs, it simply cannot have its complexity measured.
        # It is reported here so the gap is visible in one place rather than
        # discovered as a quiet "not measured" in a review months later.
        scaling_fault = validate_scaling_spec(problem.get("scaling"))
        if scaling_fault is not None:
            problems.append(f"{where}: {scaling_fault}")

    return problems
