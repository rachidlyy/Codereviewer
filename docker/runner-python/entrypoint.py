"""Case loop that runs inside the runner container.

Reads one JSON payload from stdin and writes one sentinel-prefixed JSON line
per test case to stdout, in order.

It runs inside a hardened, network-less container. Its job is to give each test
case its own child process, so that a per-case timeout kills only that child
instead of the whole run, and so that a hard crash (``os._exit``, a segfault) in
student code cannot take the remaining cases down with it.

stdin::

    {"code": str, "entrypoint": str, "memory_limit": str | null,
     "budget": float, "cases": [{"index": int, "name": str, "args": [...],
                                 "timeout": float}]}

stdout, one line per case::

    __CODERUNNER_RESULT__{"index": 1, "ok": true, "serialisable": true,
                          "actual": ..., "actual_repr": "...",
                          "compute": 0.0012, "elapsed": 0.031, "stdout": "...",
                          "exit_code": 0, "signal": null, "oom_killed": false}

then one final line with submission-level sandbox facts::

    __CODERUNNER_SANDBOX__{"memory_limit_bytes": 536870912,
                           "memory_peak_bytes": 21336064, "oom_killed": false}

``oom_killed`` is read from the cgroup's own ``oom_kill`` counter before and
after each case, so an out-of-memory kill is attributed to the case that
caused it rather than guessed at from a SIGKILL - the two are otherwise
indistinguishable from the child's return code alone.

The payload deliberately carries **no expected values**. Comparison happens in
the API process, so the answer never enters the container and cannot be read by
the code being tested.

Unlike the host, this runs on Linux, so ``subprocess.run(timeout=...)`` is
enough - there is no need for the SIGALRM workaround that Windows would force.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

HARNESS_PATH = "/opt/runner/harness.py"
RESULT_SENTINEL = "__CODERUNNER_RESULT__"

#: Fallback when a case does not carry its own limit. The API always sends one.
DEFAULT_TIMEOUT = 3.0

#: Fallback whole-submission budget. The API always sends one; this only covers
#: a hand-run payload.
DEFAULT_BUDGET = 20.0

#: Where the per-case child runs. A size-capped tmpfs at run time, so a
#: submission cannot fill the disk.
WORKDIR = "/work"

# cgroup v2 accounting. The container is limited with ``--memory``, so these
# describe the whole submission rather than one case - but ``oom_kill`` is a
# monotonic counter, so reading it before and after a case attributes an OOM
# to that case exactly instead of inferring it from a SIGKILL.
CGROUP_EVENTS = "/sys/fs/cgroup/memory.events"
CGROUP_PEAK = "/sys/fs/cgroup/memory.peak"
CGROUP_MAX = "/sys/fs/cgroup/memory.max"

#: Emitted once, after the last case, with submission-level sandbox facts.
SANDBOX_SENTINEL = "__CODERUNNER_SANDBOX__"


def _read_cgroup_int(path: str) -> int | None:
    """Read a single integer out of a cgroup file, or None if unavailable.

    Returns None rather than raising: these files are a bonus, not a
    requirement, and the runner has to work unchanged if a future kernel or
    runtime does not expose them.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    if text == "max":  # cgroup's spelling of "no ceiling"
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _oom_kills() -> int:
    """The container's cumulative OOM-kill count, or 0 when unreadable."""
    try:
        with open(CGROUP_EVENTS, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition(" ")
                if key == "oom_kill":
                    return int(value)
    except (OSError, ValueError):
        pass
    return 0


def sandbox_facts() -> dict:
    """Submission-level memory facts, read once after the last case.

    ``memory.peak`` is a high-water mark for the whole container and cannot be
    reset without root, so it is reported per submission rather than per case.
    """
    return {
        "memory_limit_bytes": _read_cgroup_int(CGROUP_MAX),
        "memory_peak_bytes": _read_cgroup_int(CGROUP_PEAK),
        "oom_killed": _oom_kills() > 0,
    }


def _parse_harness_output(stdout: str) -> dict | None:
    """Extract the sentinel-prefixed JSON line the harness prints."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_SENTINEL):
            try:
                return json.loads(line[len(RESULT_SENTINEL) :])
            except json.JSONDecodeError:
                return None
    return None


def _killed_message(returncode: int, memory_limit: str | None, oom_killed: bool) -> str:
    """Explain a child that died without producing output.

    A process killed by the kernel prints nothing at all, so without this the
    student is told only "the sandbox produced no result" - which is true and
    useless.

    ``oom_killed`` comes from the cgroup's own counter, so the memory case is
    *known* rather than guessed. A bare SIGKILL is genuinely ambiguous - the
    cgroup OOM killer and an external ``docker kill`` look identical from the
    child's return code - so the two are reported differently on purpose.
    """
    signal_number = -returncode

    if oom_killed:
        limit = f" of {memory_limit}" if memory_limit else ""
        return (
            f"Your program ran out of memory - the sandbox ceiling{limit} was "
            "reached. Look for a structure that grows without bound, or an "
            "input you never stop copying."
        )
    if signal_number == 9:
        return "Your program was stopped by the sandbox before it finished."
    if signal_number == 11:
        return "Your program crashed the interpreter (segmentation fault)."
    if signal_number == 6:
        return "Your program aborted the interpreter."
    return f"Your program was killed by signal {signal_number} before it produced a result."


def _exit_facts(returncode: int | None) -> dict:
    """Split a return code into an exit code and a signal number.

    ``subprocess`` reports a signalled child as a negative return code, which
    is compact but reads badly in an API response. -9 becomes
    ``{"exit_code": None, "signal": 9}``.
    """
    if returncode is None:
        return {"exit_code": None, "signal": None}
    if returncode < 0:
        return {"exit_code": None, "signal": -returncode}
    return {"exit_code": returncode, "signal": None}


def run_case(case: dict, code: str, entrypoint: str, memory_limit: str | None = None) -> dict:
    """Run one test case in its own child process and return its outcome."""
    index = case.get("index")
    timeout = float(case.get("timeout") or DEFAULT_TIMEOUT)

    payload = json.dumps(
        {
            "code": code,
            "entrypoint": entrypoint,
            "args": case.get("args") or [],
        }
    )

    # Snapshot the OOM counter so an out-of-memory kill can be attributed to
    # this case rather than to the submission as a whole.
    oom_before = _oom_kills()

    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-I", HARNESS_PATH],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=WORKDIR,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "index": index,
            "ok": False,
            "error_type": "timeout",
            "message": f"Exceeded the {timeout:g}s time limit for this test case.",
            "elapsed": time.perf_counter() - started,
            "exit_code": None,
            "signal": 9,
            "oom_killed": _oom_kills() > oom_before,
        }
    except OSError as exc:
        return {
            "index": index,
            "ok": False,
            "error_type": "runtime",
            "message": f"Could not start the interpreter inside the sandbox: {exc}",
            "elapsed": time.perf_counter() - started,
            "exit_code": None,
            "signal": None,
            "oom_killed": False,
        }

    elapsed = time.perf_counter() - started
    oom_killed = _oom_kills() > oom_before
    facts = _exit_facts(completed.returncode)

    reply = _parse_harness_output(completed.stdout)
    if reply is None:
        # A killed child writes nothing, so the return code plus the OOM
        # counter are the only evidence about why.
        if completed.returncode is not None and completed.returncode < 0:
            message = _killed_message(completed.returncode, memory_limit, oom_killed)
        else:
            detail = (completed.stderr or completed.stdout or "no output").strip()
            message = f"The sandbox produced no result. {detail[:300]}"
        return {
            "index": index,
            "ok": False,
            "error_type": "runtime",
            "message": message,
            "elapsed": elapsed,
            "oom_killed": oom_killed,
            **facts,
        }

    reply["index"] = index
    reply["elapsed"] = elapsed
    reply["oom_killed"] = oom_killed
    reply.update(facts)
    return reply


def _emit(result: dict) -> None:
    """Write one result line and flush immediately.

    Flushing per case matters: if the API process has to kill the container on
    its own backstop timeout, the cases that already finished are still
    readable. Buffered output would be lost with the container.
    """
    sys.stdout.write(RESULT_SENTINEL + json.dumps(result) + "\n")
    sys.stdout.flush()


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _emit(
            {
                "ok": False,
                "error_type": "runtime",
                "message": f"The sandbox could not read its request: {exc}",
            }
        )
        return

    code = payload.get("code", "")
    entrypoint = payload.get("entrypoint", "")
    cases = payload.get("cases") or []
    # Passed in rather than read from the environment so the message can name
    # the actual ceiling, and so it stays correct if the limit is changed.
    memory_limit = payload.get("memory_limit")
    budget = float(payload.get("budget") or DEFAULT_BUDGET)

    if not cases:
        _emit(
            {
                "ok": False,
                "error_type": "runtime",
                "message": "The sandbox received no test cases.",
            }
        )
        return

    # The whole-submission budget is enforced here as well as on the host. The
    # host's backstop kills the container, which loses any case that had not
    # started yet; enforcing it in here means the container always ends on its
    # own terms and every case still gets an honest line.
    deadline = time.perf_counter() + budget

    for case in cases:
        if time.perf_counter() > deadline:
            _emit(
                {
                    "index": case.get("index"),
                    "ok": False,
                    "error_type": "timeout",
                    "message": "Submission exceeded the total time budget.",
                    "elapsed": 0.0,
                    "exit_code": None,
                    "signal": None,
                    "oom_killed": False,
                }
            )
            continue
        # One bad case must not abort the rest: every case gets a line.
        try:
            _emit(run_case(case, code, entrypoint, memory_limit))
        except BaseException as exc:  # noqa: BLE001 - last-resort guard
            _emit(
                {
                    "index": case.get("index"),
                    "ok": False,
                    "error_type": "runtime",
                    "message": f"{type(exc).__name__}: {exc}",
                    "exit_code": None,
                    "signal": None,
                    "oom_killed": False,
                }
            )

    # One final line with submission-level sandbox facts. Sent after the cases
    # so that a container killed mid-run still yields everything above it.
    sys.stdout.write(SANDBOX_SENTINEL + json.dumps(sandbox_facts()) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
