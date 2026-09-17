"""In-memory problem catalogue.

This is intentionally a plain Python data structure - the MVP has no
database (see plan section 17). Each record carries the public fields the
frontend renders plus `entrypoint`, the name of the function the code
runner must call for that problem.

To migrate to PostgreSQL later, only the accessor functions at the bottom
of this module need to change.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Example(TypedDict):
    input: str
    output: str


class Problem(TypedDict):
    id: int
    title: str
    difficulty: str
    category: str
    description: str
    examples: list[Example]
    starter: str
    tags: list[str]
    entrypoint: str


#: Fields returned by the list endpoint. `starter` and `entrypoint` are
#: held back so the list payload stays small; the detail endpoint adds them.
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
#: knows what code to seed the editor with and what will be tested.
DETAIL_FIELDS = ("starter", "entrypoint")


PROBLEMS: list[Problem] = [
    {
        "id": 1,
        "title": "Contains Duplicate",
        "difficulty": "Easy",
        "category": "Arrays",
        "tags": ["Arrays", "Hash Table"],
        "description": (
            "Given an integer array nums, return true if any value appears "
            "at least twice in the array, and return false if every element "
            "is distinct."
        ),
        "examples": [
            {"input": "[1, 2, 3, 1]", "output": "true"},
            {"input": "[1, 2, 3, 4]", "output": "false"},
        ],
        "starter": (
            "def containsDuplicate(nums):\n"
            "    # Write your solution here\n"
            "    pass"
        ),
        "entrypoint": "containsDuplicate",
    },
    {
        "id": 2,
        "title": "Two Sum",
        "difficulty": "Easy",
        "category": "Arrays",
        "tags": ["Arrays", "Hash Table"],
        "description": (
            "Given an array of integers nums and an integer target, return "
            "the indices of the two numbers that add up to target. You may "
            "assume each input has exactly one solution."
        ),
        "examples": [
            {"input": "nums = [2, 7, 11, 15], target = 9", "output": "[0, 1]"},
            {"input": "nums = [3, 2, 4], target = 6", "output": "[1, 2]"},
        ],
        "starter": (
            "def twoSum(nums, target):\n"
            "    # Write your solution here\n"
            "    pass"
        ),
        "entrypoint": "twoSum",
    },
    {
        "id": 3,
        "title": "Valid Anagram",
        "difficulty": "Easy",
        "category": "Strings",
        "tags": ["Strings", "Hash Table"],
        "description": (
            "Given two strings s and t, return true if t is an anagram of s, "
            "and false otherwise. An anagram uses exactly the same "
            "characters with the same counts."
        ),
        "examples": [
            {"input": 's = "anagram", t = "nagaram"', "output": "true"},
            {"input": 's = "rat", t = "car"', "output": "false"},
        ],
        "starter": (
            "def isAnagram(s, t):\n"
            "    # Write your solution here\n"
            "    pass"
        ),
        "entrypoint": "isAnagram",
    },
    {
        "id": 4,
        "title": "Binary Search",
        "difficulty": "Easy",
        "category": "Arrays",
        "tags": ["Arrays", "Binary Search"],
        "description": (
            "Given a sorted array of integers nums and an integer target, "
            "return the index of target if it exists, otherwise return -1. "
            "Your solution should run in O(log n) time."
        ),
        "examples": [
            {
                "input": "nums = [-1, 0, 3, 5, 9, 12], target = 9",
                "output": "4",
            },
            {
                "input": "nums = [-1, 0, 3, 5, 9, 12], target = 2",
                "output": "-1",
            },
        ],
        "starter": (
            "def search(nums, target):\n"
            "    # Write your solution here\n"
            "    pass"
        ),
        "entrypoint": "search",
    },
    {
        "id": 5,
        "title": "Maximum Subarray",
        "difficulty": "Medium",
        "category": "Dynamic Programming",
        "tags": ["Arrays", "Dynamic Programming"],
        "description": (
            "Given an integer array nums, find the contiguous subarray "
            "containing at least one number which has the largest sum, and "
            "return that sum."
        ),
        "examples": [
            {"input": "[-2, 1, -3, 4, -1, 2, 1, -5, 4]", "output": "6"},
            {"input": "[5, 4, -1, 7, 8]", "output": "23"},
        ],
        "starter": (
            "def maxSubArray(nums):\n"
            "    # Write your solution here\n"
            "    pass"
        ),
        "entrypoint": "maxSubArray",
    },
]


_BY_ID: dict[int, Problem] = {problem["id"]: problem for problem in PROBLEMS}


def list_problems() -> list[Problem]:
    """Return every problem, in catalogue order."""
    return list(PROBLEMS)


def get_problem(problem_id: int) -> Problem | None:
    """Return a single problem, or None when the id is unknown."""
    return _BY_ID.get(problem_id)


def problem_exists(problem_id: int) -> bool:
    return problem_id in _BY_ID


def to_public(problem: Problem, *, include_entrypoint: bool = False) -> dict[str, Any]:
    """Project a problem record down to the API-safe field set.

    With ``include_entrypoint`` the detail-only fields (starter code and the
    function name the runner calls) are added on top of the list fields.
    """
    fields = PUBLIC_FIELDS + (DETAIL_FIELDS if include_entrypoint else ())
    return {field: problem[field] for field in fields}  # type: ignore[literal-required]
