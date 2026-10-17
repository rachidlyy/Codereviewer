"""Python code execution against predefined test cases.

Each test case runs in its own isolated child process (see
``_runner_harness.py``) with a hard timeout, so a slow or crashing
submission can never affect the API server.

This module owns three things that used to be split between itself and the
harness, and are now deliberately centralised:

* **the arguments** - ``generate`` specs are expanded here, so every language
  harness receives the same concrete values;
* **the comparison** - ``expected`` is never sent to the harness, so student
  code cannot read the answer, and the tolerance rules exist once instead of
  once per language;
* **the result shape** - ``passed``, per-case ``elapsed`` and captured
  ``stdout`` are assembled here.

This module is the single place that knows how code gets executed. Swapping
the local subprocess runner for a Docker sandbox means reimplementing
``run_submission`` and nothing else (see plan section 3).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, NamedTuple, Sequence
from uuid import uuid4

from app import config
from app.data.problems import Problem, languages_for, scaling_spec
from app.data.scaling import DEFAULT_REPS, DEFAULT_SIZES, BadScaling, resolve_scaling_args
from app.data.test_cases import BadCase, TestCase, get_test_cases, resolve_args
from app.services._runner_harness import RESULT_SENTINEL

HARNESS_PATH = Path(__file__).resolve().parent / "_runner_harness.py"

#: Marks the container's final metadata line.
#:
#: Mirrors ``SANDBOX_SENTINEL`` in ``docker/runner-python/entrypoint.py``, which
#: cannot be imported from here - it is a container-side script, not part of
#: this package. The two literals are asserted equal by
#: ``scripts/check_runner.py`` section 11, because a silent drift would mean
#: the sandbox metadata quietly disappears from every response. The same guard
#: covers ``RESULT_SENTINEL``, which is defined in both files and is far more
#: dangerous if it drifts: every submission would report "produced no result".
SANDBOX_SENTINEL = "__CODERUNNER_SANDBOX__"

#: Caps on the structured values sent to the UI for diffing.
#:
#: The reprs are already capped in the harness, but these travel as real JSON
#: so the frontend does not have to reimplement Python's literal syntax. Check
#: the length *before* serialising, so a 10-million-element list cannot make
#: the API spend time and memory encoding a value it is about to discard.
MAX_STRUCTURED_ITEMS = 200
MAX_STRUCTURED_CHARS = 4000

#: Languages this runner can actually execute. Grows as harnesses are added:
#: ``java`` and ``cpp`` in plan phase 6.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"python", "javascript"})

#: Spelling variants that mean the same language.
_LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "mjs": "javascript",
}

#: Directory under ``docker/`` holding each language's image, so a failure can
#: name the exact Dockerfile to build rather than a generic "image missing".
_IMAGE_SUFFIX = {"python": "python", "javascript": "node"}

#: The Node harness, used when ``RUNNER_BACKEND=subprocess``.
#:
#: Unlike the Python harness this is *not* copied into the API package: the
#: sandbox image installs it from this same path, so there is one file and no
#: chance of the host and container versions drifting. ``check_runner.py``
#: section 11 asserts the Dockerfile copies from here.
NODE_HARNESS_PATH = (
    Path(__file__).resolve().parents[3] / "docker" / "runner-node" / "harness.js"
)

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


class UnsupportedLanguage(ValueError):
    """The runner cannot execute the requested language."""


def normalise_language(raw: str | None) -> str:
    """Map spelling variants onto the canonical language name."""
    value = (raw or "python").strip().lower()
    return _LANGUAGE_ALIASES.get(value, value)


def resolve_language(problem: Problem, raw: str | None) -> str:
    """Validate a requested language against the runner *and* the problem.

    Two distinct failures, because they need different answers: a language the
    runner cannot execute at all, versus one it can but this particular problem
    does not offer. The second is what a half-migrated catalogue looks like.
    """
    language = normalise_language(raw)

    if language not in SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
        raise UnsupportedLanguage(
            f"'{raw}' is not supported yet. Available languages: {supported}."
        )

    if language not in languages_for(problem):
        raise UnsupportedLanguage(
            f"'{problem['title']}' is not available in {language} yet."
        )

    return language


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


def _node_executable() -> str:
    """Node interpreter used for student code on the host backend.

    ``shutil.which`` rather than a hardcoded path: this machine has Node in two
    places (a system install and the managed toolchain), and which of them is on
    the API server's PATH is not something to guess. An explicit
    ``NODE_EXECUTABLE`` wins when both are wrong.
    """
    if config.NODE_EXECUTABLE:
        return config.NODE_EXECUTABLE
    found = shutil.which("node")
    if found:
        return found
    # Returned rather than raised: the spawn below turns a missing interpreter
    # into a per-case message naming Node, which is what the student needs to
    # see. Raising here would fail the whole request instead.
    return "node"


class _Runtime(NamedTuple):
    """What the host backend needs in order to execute one language.

    Only the subprocess path needs this. The sandboxed path does not, because
    the image's ``ENTRYPOINT`` already knows which interpreter to use - which is
    exactly the benefit of putting each language in its own image.
    """

    executable: str
    harness: Path
    flags: list[str]
    label: str


def _runtime(language: str) -> _Runtime:
    if language == "javascript":
        return _Runtime(_node_executable(), NODE_HARNESS_PATH, [], "Node")
    # ``-I`` is load-bearing: isolated mode ignores PYTHON* environment
    # variables and the user site directory, so nothing in the environment can
    # influence the code being tested.
    return _Runtime(_python_executable(), HARNESS_PATH, ["-I"], "the Python interpreter")


# --------------------------------------------------------------------------
# Comparison - the only place the rules exist
# --------------------------------------------------------------------------


def _values_match(actual: Any, expected: Any) -> bool:
    """Compare a returned value to the expected one, a little forgivingly.

    Exact equality is tried first. Beyond that we tolerate two common sources
    of spurious failure in an educational setting:

    * returning ``(0, 1)`` where ``[0, 1]`` was expected (and vice versa);
    * returning ``4.0`` where ``4`` was expected.

    ``True == 1`` is Python's own rule and is left alone: for a problem whose
    answer is a boolean, returning 1 is a real answer, and failing it would
    teach the wrong lesson.
    """
    if actual == expected:
        return True

    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            return False
        return all(_values_match(a, b) for a, b in zip(actual, expected))

    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)

    return False


def _unordered_match(actual: Any, expected: Any) -> bool:
    """Match two sequences as multisets, for answers where order is free."""
    if not isinstance(actual, (list, tuple)) or not isinstance(expected, (list, tuple)):
        return False
    if len(actual) != len(expected):
        return False

    remaining = list(expected)
    for item in actual:
        for index, candidate in enumerate(remaining):
            if _values_match(item, candidate):
                remaining.pop(index)
                break
        else:
            return False
    return True


def _compare(actual: Any, expected: Any, comparator: str | None) -> bool:
    if comparator == "unordered":
        return _unordered_match(actual, expected)
    return _values_match(actual, expected)


def _recover_repr(actual_repr: str) -> tuple[bool, Any]:
    """Turn a harness ``actual_repr`` back into a value, where possible.

    The harness falls back to ``repr`` for values JSON cannot carry (a set, a
    custom object). ``literal_eval`` recovers the common cases; when it cannot,
    the caller compares the two reprs as text.
    """
    try:
        return True, ast.literal_eval(actual_repr)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _structured(value: Any) -> Any:
    """The value as real JSON for the UI to diff, or None if that is unwise.

    Sent alongside the reprs so the frontend can mark *which* index differs
    instead of printing two blobs of text. Sending the value rather than the
    repr means the frontend never has to parse Python literals - ``True``,
    ``None`` and tuples are exactly the cases a hand-written parser gets wrong.

    None means "fall back to comparing reprs": either the value is too big, or
    it is not JSON-representable at all (a set, a custom object). Returning
    None is always safe - the reprs are still there.
    """
    if isinstance(value, (list, tuple, dict)) and len(value) > MAX_STRUCTURED_ITEMS:
        return None
    try:
        encoded = json.dumps(value)
    except (TypeError, ValueError, RecursionError):
        return None
    if len(encoded) > MAX_STRUCTURED_CHARS:
        return None
    return value


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def check_syntax(code: str, language: str = "python") -> dict[str, Any] | None:
    """Compile-only check so a syntax error fails fast and once.

    ``compile`` parses without executing, so this is safe to run in-process.
    Returns an error dict, or None when the code parses cleanly.

    Python-only by nature. For any other language this returns None and the
    syntax error is reported by that language's harness instead, which costs one
    subprocess but needs no in-process parser per language.

    The ``language`` guard is load-bearing, not decorative: this function used to
    be called unconditionally, which was harmless while Python was the only
    language and would have made **every JavaScript submission report a Python
    syntax error** the moment a second language existed. ``compile`` on JS source
    raises, so the guard is what stops that.
    """
    if language != "python":
        return None

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


# --------------------------------------------------------------------------
# Backend A: host subprocess, one child process per test case
# --------------------------------------------------------------------------


def _run_case_subprocess(
    code: str,
    test_case: TestCase,
    entrypoint: str,
    timeout: float,
    language: str,
) -> tuple[dict[str, Any], float]:
    """Execute a single test case on the host. Returns (outcome, elapsed)."""
    try:
        args = resolve_args(test_case)
    except BadCase as exc:
        # A malformed test case is our bug, not the student's - but it must not
        # take the request down. Reporting it as a failure for this case keeps
        # the other cases meaningful and the message names the cause.
        return (
            {
                "passed": False,
                "error_type": "runtime",
                "message": str(exc),
                "exit_code": None,
                "signal": None,
                "oom_killed": None,
            },
            0.0,
        )

    payload = json.dumps({"code": code, "entrypoint": entrypoint, "args": args})
    runtime = _runtime(language)

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="codereviewer-run-") as workdir:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [runtime.executable, *runtime.flags, str(runtime.harness)],
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
                "exit_code": None,
                "signal": 9,
                "oom_killed": None,
            },
            elapsed,
        )
    except OSError as exc:
        elapsed = time.perf_counter() - started
        return (
            {
                "passed": False,
                "error_type": "runtime",
                "message": f"Could not start {runtime.label}: {exc}",
                "exit_code": None,
                "signal": None,
                "oom_killed": None,
            },
            elapsed,
        )

    elapsed = time.perf_counter() - started
    reply = _parse_harness_output(completed.stdout)
    if reply is None:
        detail = (completed.stderr or completed.stdout or "no output").strip()
        return (
            {
                "passed": False,
                "error_type": "runtime",
                "message": f"The runner produced no result. {detail[:300]}",
                "exit_code": None,
                "signal": None,
                "oom_killed": None,
            },
            elapsed,
        )

    # Same shape as the container path so the response is backend-independent.
    # There is no cgroup on the host, so memory facts are honestly None rather
    # than guessed at.
    returncode = completed.returncode
    reply["exit_code"] = returncode if returncode is not None and returncode >= 0 else None
    reply["signal"] = -returncode if returncode is not None and returncode < 0 else None
    reply.setdefault("oom_killed", None)

    return _verdict(reply, test_case), elapsed


def _execute_subprocess(
    cases: list[TestCase], code: str, entrypoint: str, language: str
) -> list[tuple[dict[str, Any], float]]:
    """One host process per case.

    Correct, but expensive on Windows: spawning *any* process here costs
    ~0.6-1.0s (process creation plus Defender scanning the venv), so a
    four-case problem pays ~3.8s of pure overhead. See the plan's risk table.

    The whole-submission budget is enforced here because there is no container
    to fall back on. Every case still gets an outcome, so the UI always has one
    row per test case.
    """
    outcomes: list[tuple[dict[str, Any], float]] = []
    deadline = time.perf_counter() + config.SUBMISSION_TIMEOUT_SECONDS

    for case in cases:
        if time.perf_counter() > deadline:
            outcomes.append(
                (
                    {
                        "passed": False,
                        "error_type": "timeout",
                        "message": "Submission exceeded the total time budget.",
                        "exit_code": None,
                        "signal": None,
                        "oom_killed": None,
                    },
                    0.0,
                )
            )
            continue
        timeout = float(case.get("timeout", config.TEST_TIMEOUT_SECONDS))
        outcomes.append(_run_case_subprocess(code, case, entrypoint, timeout, language))

    return outcomes


# --------------------------------------------------------------------------
# Backend B: Docker sandbox, one hardened container per submission
# --------------------------------------------------------------------------


def _docker_command(name: str, image: str) -> list[str]:
    """The ``docker run`` invocation, with every hardening flag.

    One container runs the whole submission. The container is what isolates
    student code from the host; the child processes *inside* it are what give
    per-case timeouts. A container per case would pay startup four times over
    for no additional isolation.

    ``image`` is per language, and its ``ENTRYPOINT`` is what selects the
    interpreter - so this command is identical for every language and only the
    last argument differs.
    """
    return [
        config.DOCKER_BINARY,
        "run",
        "--rm",
        "-i",
        # Named so a container that outlives its CLI can be torn down; see
        # `_force_remove`.
        "--name",
        name,
        # No network at all. Student code cannot reach the API keys, and cannot
        # hang the run on a network call.
        "--network",
        "none",
        # Kernel-enforced ceilings. Without these a submission is a denial of
        # service against the whole machine, not just its own run.
        "--memory",
        config.RUNNER_MEMORY_LIMIT,
        "--memory-swap",
        config.RUNNER_MEMORY_LIMIT,
        "--cpus",
        config.RUNNER_CPUS,
        "--pids-limit",
        str(config.RUNNER_PIDS_LIMIT),
        # Immutable root filesystem with exactly one writable, size-capped
        # place. C: has reached 0 bytes free on this machine twice.
        "--read-only",
        "--tmpfs",
        f"/work:rw,nosuid,size={config.RUNNER_TMPFS_SIZE}",
        # Nobody, no capabilities, and no way to acquire any.
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        image,
    ]


def _force_remove(name: str) -> None:
    """Tear down a container that may still be running.

    ``subprocess.run(timeout=...)`` kills the *docker CLI*, not the container.
    Without this, a backstop timeout would leak a running container holding its
    full memory limit. ``--rm`` covers the normal path, so a failure here is
    expected and deliberately swallowed.
    """
    try:
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [config.DOCKER_BINARY, "rm", "-f", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _docker_problem(completed: subprocess.CompletedProcess[str], image: str, language: str) -> str:
    """Turn a failed ``docker run`` into something the operator can act on."""
    text = f"{completed.stderr or ''}\n{completed.stdout or ''}"
    lowered = text.lower()

    if (
        "cannot connect" in lowered
        or "error during connect" in lowered
        or "is the docker daemon running" in lowered
    ):
        return (
            "The code sandbox is unavailable: the Docker daemon is not running. "
            "Start Docker Desktop, or set RUNNER_BACKEND=subprocess in backend/.env "
            "to run without a sandbox."
        )

    if (
        "unable to find image" in lowered
        or "no such image" in lowered
        or "pull access denied" in lowered
    ):
        return (
            f"The sandbox image '{image}' is missing. Build it with: "
            f"docker build -f docker/runner-{_IMAGE_SUFFIX[language]}/Dockerfile -t {image} ."
        )

    detail = " ".join(text.split())
    return f"The code sandbox failed (exit {completed.returncode}): {detail[:300]}"


def _execute_docker(
    cases: list[TestCase],
    code: str,
    entrypoint: str,
    language: str,
    *,
    budget: float | None = None,
) -> ExecutionResult:
    """Run every case in one container.

    Returns one ``(outcome, elapsed)`` per case plus the container's own
    memory facts.
    """
    #: The whole-submission ceiling, normally from config. ``budget`` overrides
    #: it for measurement ladders, which are expected to be slow.
    submission_budget = budget if budget is not None else config.SUBMISSION_TIMEOUT_SECONDS
    image = config.runner_image(language)
    prepared: list[dict[str, Any]] = []
    pre_failed: dict[int, dict[str, Any]] = {}

    for index, case in enumerate(cases, start=1):
        try:
            args = resolve_args(case)
        except BadCase as exc:
            pre_failed[index] = {
                "passed": False,
                "error_type": "runtime",
                "message": str(exc),
                "exit_code": None,
                "signal": None,
                "oom_killed": None,
            }
            continue
        prepared.append(
            {
                "index": index,
                "name": case.get("name") or f"Test {index}",
                "args": args,
                "timeout": float(case.get("timeout", config.TEST_TIMEOUT_SECONDS)),
            }
        )

    payload = {
        "code": code,
        "entrypoint": entrypoint,
        # Sent so the sandbox can name the actual ceiling in an out-of-memory
        # message instead of saying only "no result".
        "memory_limit": config.RUNNER_MEMORY_LIMIT,
        # The container enforces the whole-submission budget itself, so it ends
        # on its own terms and reports every case. The host-side backstop below
        # is only for a container that hangs outright.
        "budget": submission_budget,
        "cases": prepared,
    }

    replies: dict[int, dict[str, Any]] = {}
    container_error: str | None = None
    #: Submission-level memory facts, read from the container's cgroup. None
    #: when the container never produced them - a dead daemon, a killed run.
    sandbox: dict[str, Any] | None = None

    if prepared:
        name = f"codereviewer-run-{uuid4().hex[:12]}"
        # The per-case limits are enforced inside the container, so this is only
        # a backstop against the container hanging outright.
        backstop = submission_budget + config.DOCKER_STARTUP_GRACE_SECONDS

        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                _docker_command(name, image),
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=backstop,
                check=False,
            )
        except subprocess.TimeoutExpired:
            container_error = (
                f"The sandbox exceeded its {backstop:g}s budget and was stopped."
            )
        except FileNotFoundError:
            container_error = (
                f"The '{config.DOCKER_BINARY}' command was not found. Install Docker, "
                "or set RUNNER_BACKEND=subprocess in backend/.env."
            )
        except OSError as exc:
            container_error = f"Could not start the sandbox: {exc}"
        finally:
            # Runs on every path, including the timeout, so a container can
            # never outlive its request.
            _force_remove(name)

        if container_error is None and completed is not None:
            # A non-zero exit with no result lines means the container itself
            # failed to start - a dead daemon, a missing image.
            if completed.returncode != 0 and RESULT_SENTINEL not in completed.stdout:
                container_error = _docker_problem(completed, image, language)
            else:
                for line in completed.stdout.splitlines():
                    if line.startswith(SANDBOX_SENTINEL):
                        try:
                            facts = json.loads(line[len(SANDBOX_SENTINEL) :])
                        except json.JSONDecodeError:
                            continue
                        if isinstance(facts, dict):
                            sandbox = facts
                        continue
                    if not line.startswith(RESULT_SENTINEL):
                        continue
                    try:
                        reply = json.loads(line[len(RESULT_SENTINEL) :])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(reply.get("index"), int):
                        replies[reply["index"]] = reply

    outcomes: list[tuple[dict[str, Any], float]] = []
    for index, case in enumerate(cases, start=1):
        if index in pre_failed:
            outcomes.append((pre_failed[index], 0.0))
            continue

        reply = replies.get(index)
        if reply is None:
            # Either the container never ran, or it died partway. Every case
            # still gets an outcome so the UI has something to show for each.
            message = container_error or "The sandbox did not report a result for this test case."
            outcomes.append(
                (
                    {
                        "passed": False,
                        "error_type": "runtime",
                        "message": message,
                        "exit_code": None,
                        "signal": None,
                        "oom_killed": None,
                    },
                    0.0,
                )
            )
            continue

        elapsed = float(reply.pop("elapsed", 0.0) or 0.0)
        reply.pop("index", None)
        outcomes.append((_verdict(reply, case), elapsed))

    return ExecutionResult(outcomes=outcomes, sandbox=sandbox)


class ExecutionResult(NamedTuple):
    """What a backend produced.

    ``outcomes`` holds one ``(outcome, elapsed)`` pair per case, in case order,
    so ``run_submission`` can shape the response without knowing which backend
    ran. ``sandbox`` carries submission-level facts the host cannot know - the
    container's memory ceiling and peak - and is None for the host backend,
    which has no cgroup to read.
    """

    outcomes: list[tuple[dict[str, Any], float]]
    sandbox: dict[str, Any] | None


def _execute(
    cases: list[TestCase],
    code: str,
    entrypoint: str,
    language: str = "python",
    *,
    budget: float | None = None,
) -> ExecutionResult:
    """Dispatch to the configured backend.

    ``budget`` overrides the whole-submission ceiling for this call only, and
    exists for measurement. A scaling ladder is *expected* to be slow at its
    largest size - that slowness is the signal - so it needs a longer leash than
    a test run, and cutting it short would silently lose the very points the
    classification depends on. The host backend ignores it, having no container
    to enforce it in.
    """
    if config.runner_backend() == "docker":
        return _execute_docker(cases, code, entrypoint, language, budget=budget)
    return ExecutionResult(
        outcomes=_execute_subprocess(cases, code, entrypoint, language),
        sandbox=None,
    )


def _verdict(reply: dict[str, Any], test_case: TestCase) -> dict[str, Any]:
    """Attach a pass/fail verdict to the harness' reply."""
    outcome: dict[str, Any] = {
        "passed": False,
        "error_type": reply.get("error_type"),
        "message": reply.get("message"),
        # How the child actually ended. ``exit_code`` is the clean exit status,
        # ``signal`` the number of the signal that killed it - a signalled
        # child has no exit code, and a clean one has no signal, so at most one
        # of the two is ever set.
        "exit_code": reply.get("exit_code"),
        "signal": reply.get("signal"),
        # From the cgroup's own counter, so this is knowledge rather than a
        # guess. None (not False) when the backend cannot report it at all -
        # the host runner has no cgroup to read.
        "oom_killed": reply.get("oom_killed"),
    }
    if reply.get("stdout"):
        outcome["stdout"] = reply["stdout"]
        # Only set when it actually happened, so the UI can explain why the
        # output stops rather than just showing an ellipsis.
        if reply.get("stdout_truncated"):
            outcome["stdout_truncated"] = True
    if reply.get("compute") is not None:
        outcome["compute"] = reply["compute"]

    expected = test_case.get("expected")
    outcome["expected"] = repr(expected)
    outcome["expected_value"] = _structured(expected)

    if not reply.get("ok"):
        return outcome

    actual_repr = reply.get("actual_repr")
    if actual_repr is not None:
        outcome["actual"] = actual_repr

    comparator = test_case.get("comparator")

    if reply.get("serialisable", True):
        actual = reply.get("actual")
        outcome["actual_value"] = _structured(actual)
    else:
        # JSON could not carry the value, so compare the repr. literal_eval
        # recovers tuples and sets; failing that, the two reprs are compared
        # as text, which is the best available evidence.
        ok, recovered = _recover_repr(actual_repr or "")
        if not ok:
            outcome["passed"] = actual_repr == repr(expected)
            return outcome
        actual = recovered
        # Recovered from a repr, so it may hold tuples or sets. Only send it
        # if it survived the round trip as JSON.
        outcome["actual_value"] = _structured(actual)

    outcome["passed"] = _compare(actual, expected, comparator)
    return outcome


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
    if any(r.get("error_type") in {"syntax", "compile", "runtime"} for r in results):
        return "error"
    return "failed"


def _summarise_error(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most useful error to surface to the student."""
    for error_type in ("syntax", "compile", "runtime", "timeout"):
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
        # Nothing ran, so there is nothing to say about the sandbox.
        "sandbox": None,
    }


def run_submission(problem: Problem, code: str, language: str = "python") -> dict[str, Any]:
    """Run a submission against every test case for the problem.

    Returns a dict matching the ``POST /api/submissions/run`` response
    contract (plan section 15), with an extra ``error`` object so the UI
    can render the friendly messages from plan section 16.

    Raises :class:`UnsupportedLanguage` when the language is not executable or
    the problem does not offer it.
    """
    resolved = resolve_language(problem, language)
    entrypoint = languages_for(problem)[resolved]["entrypoint"]

    cases = get_test_cases(problem["id"])
    if not cases:
        result = _empty_result(0)
        result["error"] = _build_error("runtime", "No test cases are configured for this problem.")
        return result

    # Fail fast on a syntax error: every case would fail identically. Python
    # only - see the note in check_syntax.
    syntax_error = check_syntax(code, resolved)
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
                "expected": repr(case.get("expected")),
                "actual_value": None,
                "expected_value": _structured(case.get("expected")),
                "elapsed": 0.0,
                "compute": 0.0,
                "stdout": None,
                # Present and False rather than omitted, so a client can treat
                # the field as always-there. The syntax branch never runs the
                # code, so there is nothing to truncate.
                "stdout_truncated": False,
                "exit_code": None,
                "signal": None,
                "oom_killed": None,
            }
            for index, case in enumerate(cases)
        ]
        result["error"] = syntax_error
        return result

    # The backend decides how the cases are executed and enforces the time
    # budget; this function only shapes the answer. Every backend returns one
    # (outcome, elapsed) pair per case, in order, so the loop below is
    # backend-agnostic.
    execution = _execute(cases, code, entrypoint, resolved)
    outcomes = execution.outcomes

    tests: list[dict[str, Any]] = []
    total_elapsed = 0.0

    for index, (outcome, elapsed) in enumerate(outcomes):
        case = cases[index]
        name = case.get("name") or f"Test {index + 1}"
        total_elapsed += elapsed

        tests.append(
            {
                "index": index + 1,
                "name": name,
                "passed": bool(outcome.get("passed")),
                "error_type": outcome.get("error_type"),
                "message": outcome.get("message"),
                "actual": outcome.get("actual"),
                "expected": outcome.get("expected", repr(case.get("expected"))),
                # Structured twins of the two reprs above, so the UI can point
                # at the differing index instead of printing two blobs. None
                # when the value is too large or not JSON-representable.
                "actual_value": outcome.get("actual_value"),
                "expected_value": outcome.get("expected_value"),
                "elapsed": round(elapsed, 4),
                "compute": round(float(outcome.get("compute") or 0.0), 6),
                "stdout": outcome.get("stdout"),
                "stdout_truncated": bool(outcome.get("stdout_truncated")),
                "exit_code": outcome.get("exit_code"),
                "signal": outcome.get("signal"),
                "oom_killed": outcome.get("oom_killed"),
            }
        )

    return {
        "status": _determine_status(tests),
        "passed": sum(1 for test in tests if test["passed"]),
        "total": len(tests),
        "execution_time": round(total_elapsed, 3),
        "tests": tests,
        "error": _summarise_error(tests),
        "sandbox": execution.sandbox,
    }


class ScalingMeasurement(NamedTuple):
    """One submission's timing ladder: raw numbers, deliberately uninterpreted.

    Deciding what the numbers *mean* is ``services/complexity.py``'s job. Keeping
    the two apart is what lets the instrument be tested on its own, and lets a
    classification rule change later without re-running anything.
    """

    sizes: list[int]
    #: Best-of-``reps`` seconds spent inside the student's own code, per size.
    #: ``None`` where that size produced no measurement - a timeout, a crash, or
    #: a budget that ran out before the case started. Never zero-filled, because
    #: a missing measurement and an instantaneous one are different facts and a
    #: zero would read as an infinitely fast solution.
    compute: list[float | None]
    #: Why a size has no measurement, in the harness' own words.
    errors: list[str | None]
    #: True when every size produced a number.
    ok: bool
    #: Why not, when ``ok`` is False.
    message: str | None


def measure_scaling(
    problem: Problem,
    code: str,
    language: str = "python",
    *,
    sizes: Sequence[int] | None = None,
    reps: int = DEFAULT_REPS,
    budget: float | None = None,
) -> ScalingMeasurement:
    """Time a submission at several input sizes, for measured complexity.

    Returns the raw ladder and never raises for a merely *slow* or *wrong*
    submission. Raises :class:`UnsupportedLanguage` for a language that cannot
    be run at all, or that this problem does not offer - the same two refusals
    :func:`run_submission` makes, so callers handle them once.

    Why this is public
    ------------------
    ``run_submission`` runs the catalogue's fixed cases and nothing else, so
    there was previously no way to time a submission at a size of your choosing.
    The only ladder in the codebase lived in ``check_runner`` and reached into
    the private ``_execute``. Execution belongs in this module, so the ladder
    does too, and ``complexity.py`` can measure without touching a private
    helper.

    ``code`` does not have to be correct, and the generated inputs carry no
    expected value at all - a measurement only needs the student's code to
    *run*. Passing a known-linear probe as ``code`` is the intended way to get
    the baseline a submission should be compared against.
    """
    resolved = resolve_language(problem, language)
    entrypoint = languages_for(problem)[resolved]["entrypoint"]

    # A measurement ladder gets a longer leash than a test run, because the
    # slowness at the largest size is the signal rather than a failure. See
    # SCALING_TIMEOUT_SECONDS for why it is a backstop and not a tuned number.
    effective_budget = budget if budget is not None else config.SCALING_TIMEOUT_SECONDS

    # Ascending, and de-duplicated. Ascending matters: if the budget runs out
    # partway through, the cheap small sizes have already reported and only the
    # expensive tail is lost. Running largest-first would throw away every point
    # to learn one.
    ladder = sorted({int(n) for n in (sizes if sizes is not None else DEFAULT_SIZES)})

    def unmeasured(message: str) -> ScalingMeasurement:
        blanks: list[None] = [None] * len(ladder)
        return ScalingMeasurement(ladder, list(blanks), list(blanks), False, message)

    if not ladder or any(n <= 0 for n in ladder):
        return unmeasured(f"Ladder sizes must be positive integers, got {ladder}.")

    spec = scaling_spec(problem)
    if spec is None:
        return unmeasured(
            "This problem declares no 'scaling' spec, so its complexity cannot be measured."
        )

    try:
        cases: list[TestCase] = [
            {
                "name": f"n={n}",
                "args": resolve_scaling_args(spec, n),
                # Generous on purpose: this measures growth, so a timeout would
                # turn a slow measurement into a missing one. The whole-ladder
                # budget is the real ceiling.
                "timeout": float(effective_budget),
            }
            for n in ladder
        ]
    except BadScaling as exc:
        return unmeasured(str(exc))

    # Fail fast on a syntax error: every size would fail identically, and this
    # costs nothing instead of a container. Python only - see `check_syntax`.
    syntax_error = check_syntax(code, resolved)
    if syntax_error is not None:
        return unmeasured(syntax_error["detail"])

    best: list[float | None] = [None] * len(ladder)
    errors: list[str | None] = [None] * len(ladder)

    for _ in range(max(int(reps), 1)):
        outcomes = _execute(cases, code, entrypoint, resolved, budget=effective_budget).outcomes
        for index, (outcome, _elapsed) in enumerate(outcomes):
            if index >= len(ladder):
                break
            compute = outcome.get("compute")
            # "Ran" means the harness produced a time and raised nothing. A case
            # that merely returned the wrong answer is still a valid
            # measurement - correctness is not this function's business.
            if outcome.get("error_type") is None and compute is not None:
                seconds = float(compute)
                # Best-of-N, not the mean: the noise here is one-sided. A
                # measurement is only ever slowed down by the machine.
                best[index] = seconds if best[index] is None else min(best[index], seconds)
            else:
                errors[index] = outcome.get("message") or (
                    f"no measurement ({outcome.get('error_type') or 'unknown'})"
                )

    missing = [ladder[i] for i, value in enumerate(best) if value is None]
    if missing:
        listed = ", ".join(str(n) for n in missing)
        return ScalingMeasurement(ladder, best, errors, False, f"No measurement at n={listed}.")
    return ScalingMeasurement(ladder, best, errors, True, None)
