# CodeReviewer — Full Demo Plan

**Status:** supersedes the one-week MVP plan (`C:\Users\erach\Downloads\plan.md`).
**Date:** 2026-09-22.
**Target:** a locally-run, feature-complete product demo — not a hosted service.

The MVP plan's §1–§19 are still accurate about the product concept, the demo path, the UI
direction, the error copy and the API contract. Its §2 ("Do NOT build yet"), §17 ("no database"),
§20 and §21 ("works without logging in") are all **void** — Phase 2 already broke them. This
document is the replacement for §2, §17, §18 and §20–§23.

The golden rule survives, reworded:

> **Every phase must leave the demo path working end to end.**
> `PROBLEM → CODE → RUN → TEST RESULTS → AI REVIEW → IMPROVEMENT` may never regress, at any
> commit, in any phase.

---

## 1. Scope decisions (locked 2026-09-22)

| Question | Decision |
|---|---|
| Delivery | **Local, feature-complete.** No hosting, no deployment, no production Clerk instance, no CI. Two dev servers as today. |
| Languages | **Four: Python, JavaScript, Java, C++.** |
| Execution isolation | **Docker sandbox, one container per submission.** |
| Priorities | Richer execution feedback · Bigger problem set · Static analysis / measured complexity |

### Explicitly out of scope

- Hosting, deployment, domains, TLS, production Clerk. Nothing in this plan assumes a public URL.
- Instructor / classroom view (considered, not selected).
- Leaderboards, social features, GitHub integration, team coding.
- AI-generated problems, learning paths, personalised recommendations.
- Redis, Celery, message queues. The app stays two processes plus Postgres plus `docker run`.

---

## 2. Blocker — read before anything else

**The multi-language Docker plan cannot start until the disk situation is fixed. This is not a
task I can do for you; it needs your decision and your hands.**

Verified 2026-09-22:

```
C:  232G total, 230G used, 1.3G free   (100%)
E:  932G total, 841G used,  92G free   (91%)

docker info -> failed to connect at npipe:////./pipe/dockerDesktopLinuxEngine
               (the Docker daemon is not running)

Docker's disk image lives at  C:\Users\erach\AppData\Local\Docker\wsl\disk
```

Four toolchain images (Python, Node, JDK, GCC) plus their layers need roughly **3–5 GB**. There is
1.3 GB free on C:. Pulling them will fail, and a failed pull on a 100%-full volume is the failure
mode that has already broken this machine's tooling twice — `agent-browser` panicking with
`os error 112` writing to `%TEMP%`, and tool calls dying with `ENOSPC`.

### Phase 0 — unblock Docker (your action)

1. **Move Docker Desktop's disk image to E:.** Settings → Resources → Advanced → *Disk image
   location* → `E:\Docker`. Docker will move the existing image. This is the single change that
   makes the rest of this plan possible, and it keeps the 92 GB of headroom on E: doing the work.
2. **Start the Docker daemon** and confirm it survives a restart.
3. **Confirm the whole thing works:** `docker run --rm alpine echo ok` must print `ok`.
4. Optional but recommended: the ~10 GB reclaimable under your user profile (`npm-cache` 3.7 G,
   `Docker` 2.5 G, `pip` 1.8 G, `Temp` 1.5 G). **I will not touch any of it without your explicit
   confirmation, file by file.**

**Exit criterion:** `docker run --rm alpine echo ok` succeeds, Docker's disk image is on `E:`, and
C: has more than 5 GB free.

Everything below Phase 0 can be *written* before Docker works, but nothing in Phase 2 onward can be
*verified* until it does.

---

## 3. The execution architecture

The current runner is a subprocess per test case on the host, with a stripped environment and a
hard timeout. That design has already been built so that swapping the backend means reimplementing
one function — `code_runner.run_submission()` — and nothing else. This plan cashes that in.

### Shape

```
POST /api/submissions/run
        │
        ▼
  code_runner.run_submission(problem, code, language)     ← unchanged signature
        │
        ├─ language → runner image lookup
        │
        ▼
  docker run --rm -i  <hardening flags>  codereviewer-runner-<lang>
        │
        │   one container per SUBMISSION
        ▼
  ┌──────────────────────────────────────────────┐
  │  container entrypoint: case loop             │
  │    for each test case:                       │
  │      spawn ONE child process                 │
  │        → write student code to a file        │
  │        → generate the driver for this case   │
  │        → compile if needed                   │
  │        → run, print result JSON              │
  │      per-case timeout kills that child only  │
  └──────────────────────────────────────────────┘
        │
        │  stdout: one sentinel-prefixed JSON line per case
        ▼
  Python parent: compare, diff, time, build the RunResponse
```

### Three decisions worth stating plainly

**One container per submission, one child process per test case.** The container is what isolates
student code from the host; the inner children are what give per-case timeouts and crash isolation.
A container per *test case* would pay 300–800 ms of startup four or five times per run for no extra
safety.

**Comparison happens in Python, not in the container.** Each language's driver prints its return
value as JSON; the parent does the comparing. This keeps `_values_match`, the expected-vs-actual
diff, and the status vocabulary in exactly one place instead of four. It is also what makes adding
Java and C++ tractable — neither needs a JSON *parser* in the container, only a small JSON
*serialiser* for the return value.

**Test arguments are serialised into the generated driver as native literals.** The driver is
generated per problem, per language, per case, from the problem's declared signature. So
`args: [[1,2,3,1]]` becomes `int[] nums = new int[]{1,2,3,1};` in Java and
`vector<int> nums{1,2,3,1};` in C++. No JSON parsing in Java or C++, and the awkward case — an
expression like `list(range(20000))` — becomes a generated loop in the driver instead of something
the container has to evaluate.

### Container hardening

```bash
docker run --rm -i \
  --network none \
  --memory 512m --memory-swap 512m \
  --cpus 1 \
  --pids-limit 128 \
  --read-only \
  --tmpfs /work:rw,nosuid,size=128m \
  --user 65534:65534 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  codereviewer-runner-python
```

- `--network none` is the important one. Student code cannot exfiltrate the API keys, and cannot
  hang the run on a network call.
- `/work` is **not** `noexec` — Java and C++ compile a binary there and must be able to run it.
  `nosuid` stays.
- `--read-only` plus a size-capped tmpfs means a submission cannot fill the disk. On this machine
  that is not a hypothetical.
- `--user 65534` (nobody) plus `--cap-drop ALL` means a container escape starts from nothing.

### The demo must survive Docker being down

`RUNNER_BACKEND=docker|subprocess`, defaulting to `docker`, with the current subprocess runner kept
in the tree. `/api/health` gains `runner_backend` and `docker_ok`. If Docker is unreachable the API
logs an error, reports it on health, and — if `RUNNER_BACKEND=subprocess` — still runs Python.

This is deliberate. Docker Desktop on Windows is the least reliable component in this stack, and a
demo that cannot run because a daemon did not start is a worse outcome than a demo without a
sandbox. **Python falls back; the other three languages do not** — they have no host toolchain
guaranteed. The UI must say so rather than failing obscurely.

---

## 4. The keystone refactor — language-agnostic test contract

**This is the most invasive change in the plan and it must land first, while the project is still
Python-only and therefore testable.**

Today a test case is a Python expression:

```python
{"name": "Basic duplicate", "input": "[1, 2, 3, 1]", "expected": "True"}
```

`"[1, 2, 3, 1]"` is not valid JavaScript, Java or C++. `"list(range(20000))"` is Python and nothing
else. The current format cannot generalise, so it is replaced before any second language exists.

### New test case format

```json
{
  "name": "Basic duplicate",
  "args": [[1, 2, 3, 1]],
  "expected": true,
  "timeout": 3.0,
  "comparator": "unordered"
}
```

- `args` — a JSON array of positional arguments. Every language's driver converts these to native
  literals.
- `expected` — JSON. Comparison is structural.
- `comparator` — optional; `exact` (default) or `unordered` (for answers where element order is not
  part of the contract).
- `timeout` — unchanged, per case.
- **`generate`** — a new optional escape hatch for the large-input case: instead of a literal,
  `{"generate": {"kind": "range", "n": 200000}}` tells each driver to build the input itself. This is
  what replaces `list(range(200000))` and is what makes the large-input performance case work in
  all four languages without a multi-megabyte literal.
  - The size has moved twice and is worth stating once here: 20,000 was too small for JavaScript
    (the naive solution finished in 0.47s), and 100,000 was still too small (2.64s against the 3s
    limit, measured on an idle machine). **200,000 is the first value with a real margin in both
    languages** — the naive solution needs 10.48s in JavaScript against 0.06s for the optimal one.
    Any future change must re-measure in *every* supported language, on an idle machine.

### New problem format

`backend/app/data/problems.json` replaces `problems.py` as the data source — a plain JSON file, so a
problem can be added without touching Python. `problems.py` becomes a thin loader and keeps its
accessor functions (`list_problems`, `get_problem`, `to_public`), so routes do not change.

```json
{
  "id": 1,
  "title": "Contains Duplicate",
  "difficulty": "Easy",
  "category": "Arrays",
  "tags": ["Arrays", "Hash Table"],
  "description": "...",
  "examples": [{"input": "[1, 2, 3, 1]", "output": "true"}],
  "languages": {
    "python": {
      "entrypoint": "containsDuplicate",
      "params": ["list[int]"],
      "returns": "bool",
      "starter": "def containsDuplicate(nums):\n    pass"
    },
    "javascript": {
      "entrypoint": "containsDuplicate",
      "params": ["number[]"],
      "returns": "boolean",
      "starter": "function containsDuplicate(nums) {\n}"
    },
    "java": { "entrypoint": "containsDuplicate", "params": ["int[]"], "returns": "boolean", "starter": "..." },
    "cpp":  { "entrypoint": "containsDuplicate", "params": ["vector<int>&"], "returns": "bool", "starter": "..." }
  }
}
```

### What this breaks, and where

| File | Change |
|---|---|
| `app/data/test_cases.py` | Format change; becomes `test_cases.json` alongside problems |
| `app/data/problems.py` | Becomes a loader over `problems.json`; `PUBLIC_FIELDS`/`DETAIL_FIELDS` give way to a language map |
| `app/services/code_runner.py` | `run_submission(problem, code, language)`; comparison + diffing centralised here |
| `app/services/_runner_harness.py` | Becomes the **Python** harness; siblings added per language |
| `app/schemas/submission.py` | `ProblemDetail.starter`/`entrypoint` → `languages: dict[str, LanguageSpec]`; `TestCaseResult` gains `elapsed`, `stdout`; `RunError` gains a `compile` type |
| `app/routes/submissions.py` | Passes `language` through (already accepted in `RunRequest`, currently ignored) |
| `frontend/src/types/index.ts` | Mirrors the schema change — this is the contract, keep it honest |
| `frontend/src/components/EditorPanel.tsx` | Language selector; per-language starter code |
| `backend/scripts/smoke_test.py` | New format; the starter-code assertion must run per language |

**Exit criterion for this phase:** all 5 problems and 17 test cases run green through the new
format on the **existing subprocess runner**, and problem 1 still produces exactly `3/4 tests
passed` with the nested-loop solution. If the demo's headline number changes, the refactor is wrong.

---

## 5. Phases

Each phase is independently demonstrable. Do not start the next one until the exit criterion holds.

### Phase 0 — Unblock Docker
*Prerequisite. See §2. Requires your action.*

**Exit:** `docker run --rm alpine echo ok` succeeds; disk image on `E:`; C: has >5 GB free.

---

### Phase 1 — Language-agnostic test and problem contract
*See §4. No Docker, no new languages — Python only, so the refactor is provable.*

**Exit:** 5 problems / 17 cases green on the subprocess runner; problem 1 still yields `3/4`.

---

### Phase 2 — Docker execution backend, Python only
- `docker/runner-python/Dockerfile` — `python:3.12-slim`, non-root user, the case-loop entrypoint.
- `code_runner.run_submission()` reimplemented against `docker run`; the subprocess path retained
  behind `RUNNER_BACKEND`.
- Compile-free, so the simplest possible first container: it proves the plumbing before any
  compiler enters the picture.
- `/api/health` reports `runner_backend` and `docker_ok`.

**Exit:** identical results to Phase 1 for every problem; `--network none` confirmed by a submission
that tries to open a socket; an infinite loop is killed at the per-case timeout; a submission that
allocates 1 GB dies rather than taking the machine down.

**DONE 2026-09-22.** `scripts/check_runner.py` reports **69 passed / 0 failed / 0 skipped** with
`RUNNER_BACKEND=docker` (**60 / 0 / 4 skipped** on `subprocess`, where the isolation, OOM,
container-count and image-staleness probes have nothing to probe), and the four isolation probes are
now permanent section 10 of that script rather than a one-off manual test. Problem 1's demo number is
unchanged: naive scores exactly 3/4, failing only the performance case, by timeout at ~3.01s.

#### What Phase 2 cost, measured

| Stage | Cost | Notes |
|---|---|---|
| Container create + destroy | **1.7–2.3s** | once per submission, not per case |
| Python spawn inside the container | 0.043s | |
| + stdlib imports (`json`, `io`, `contextlib`) | **+0.24s** | so ~0.26s per case, warm |
| Windows host process spawn, for comparison | 0.59–1.0s | what Phase 2 replaced |

**The sandbox is a latency cost, and it is the right trade.** Problem 1 with a correct solution
takes **2.25–2.62s wall clock** warm (2.45s median over four runs), of which ~0.7s is the case work
and the rest is container lifecycle plus API overhead. The naive demo solution takes **4.80–4.86s**,
because it additionally pays the 3s timeout on the performance case. A cold first run costs ~4.8s
while the image layers page in from the vhdx — worth knowing before a demo, so run one throwaway
submission after starting the daemon.

> **Correction, 2026-09-22 (same day, later).** The 2.25–2.62s figure above **is not reproducible.**
> Re-running the identical submission four times in a row gave **4.65s, 3.87s, 3.95s and 5.14s**, with
> per-case `elapsed` drifting from 0.166s to **0.25–0.47s**, and a full suite run under load reached
> **8.17s**. Nothing changed in the runner between the two sets of measurements — it is Docker Desktop
> on Windows and machine load. Treat the sandbox as **~4–5s per submission, occasionally more**, and
> do not quote the 2.45s median in a demo script. The per-case numbers below (container 1.7–2.3s,
> in-container spawn 0.26s) were measured once and may be similarly optimistic.

**The original exit criterion — "problem 1 under 2s for a correct solution" — was written before
anything was measured, and warm it is missed by about 0.3s.** It was replaced by "under 3s wall clock
warm, with per-case `compute` under 50ms". **That replacement has now been withdrawn too**, for the
reason above: no absolute wall-clock bound on this machine is both tight enough to mean something and
stable enough not to fire spuriously. What survives is the *structural* property, which is asserted
directly and is load-independent — **one `docker run` per submission, not one per case** (counted by
patching `subprocess.run` in `check_runner.py` section 3). A container per case would cost four times
the lifecycle overhead for no extra isolation, and that is the regression worth guarding.

Note the sandbox is still slower than the unsandboxed host runner (~3.4–4.7s) for a *small* problem,
and it will win outright once Phase 6 needs a compiler, because there is no JDK or g++ on this machine
and compiling untrusted code on the host is not an option.

#### Two traps found while building this, both worth keeping

1. **A container-level budget is needed as well as a per-case one.** Per-case limits alone let 12
   cases × 3s exceed the host's backstop, at which point the host kills the container and every
   case that had not started is lost. `entrypoint.py` now enforces `SUBMISSION_TIMEOUT_SECONDS`
   itself and reports the remaining cases honestly; the host backstop is only for a container that
   hangs outright.
2. **`subprocess.run(timeout=...)` kills the docker CLI, not the container.** Without `--rm`, a
   unique `--name` and a `finally` that force-removes it, a timed-out run leaks a container. Section
   10 checks for leftovers after every run.

#### A warning for Phase 5, discovered here

**Timing alone classifies less reliably than it looks.** `compute` is sound — a function that
ignores its input stays flat (1.26x over 16x input), so it is genuinely measuring the student's code
and not the interpreter boot. But *what you measure it on matters*:

- problem 1's own reference solution builds a hash set, and hash-table growth is allocation-bound
  and rehashes in steps. Measured per doubling over n=3000→48000 it gave **2.54x, 2.68x, 3.15x**
  against an ideal 2.0x — noisy enough that a naive classifier would call it superlinear.
- a plain `sum(nums)` scan over the same ladder gave **1.93x**, essentially exact.
- the naive nested-loop solution gave **4.09x, 4.11x** against an ideal 4.0x — very stable.

So the linear/quadratic margin is real but not enormous, and the calibration benchmark must not
itself be lumpy. Phase 5 therefore pairs the measurement with a static read of the code, and
`check_runner.py` section 5b asserts the separation rather than assuming it.

---

### Phase 3 — Execution feedback
This is the phase that makes the product feel finished, and it is cheap relative to its effect.

- **Render captured `stdout`.** The harness already captures student output and caps it at 4000
  chars; `TestResults.tsx` currently drops it on the floor. A teaching tool where `print()` does
  nothing is a teaching tool nobody can debug with.
- **Per-case timing.** `run_submission` already times each case individually and then sums them;
  surface the per-case numbers and keep the total.
- **Better expected-vs-actual.** The existing `failure-detail` block works for scalars. Add
  truncation for long values and a structural diff for lists, so `[0, 1]` vs `[1, 0]` reads as a
  mismatch rather than two blobs of text.
- **Container metadata on the error path.** Exit code, whether it was killed, peak memory.

**Exit:** a submission that prints 10,000 lines shows bounded output instead of hanging the page; a
wrong-answer case shows a readable diff; a killed submission says it was killed and why.

**DONE 2026-09-22.** `check_runner.py` reports **69 passed / 0 failed / 0 skipped** on `docker` and
**60 / 0 / 4 skipped** on `subprocess`; `tsc --noEmit` exit 0; live health green. All three exit
criteria are asserted by section 12 rather than checked by eye, on both backends:

| Criterion | Measured |
|---|---|
| 10,000 printed lines stay bounded | 4,016 chars per case (the harness' 4,000-char cap plus its marker), `stdout_truncated: true` on every case, whole response **19.3 KB** |
| a wrong answer shows a readable diff | `expected_value: [0, 1]` vs `actual_value: [1, 0]`, arriving as real JSON rather than two reprs |
| a killed submission says why | `oom_killed: true`, `signal: 9`, `exit_code: null`, message naming the ceiling; peak memory **536,870,912 bytes == the 512 MB limit** |

#### What was built

- `_CappedBuffer` in the harness replaces `io.StringIO`. A runaway `print` loop used to accumulate
  every byte, exhaust the container's ceiling, and be reported as an out-of-memory failure — true and
  useless, because the student's actual mistake was printing too much. Capping on write keeps memory
  flat regardless of volume.
- The entrypoint reads the cgroup's **`oom_kill` counter before and after each case**, so an OOM is
  *attributed to a specific case* rather than inferred from a bare SIGKILL. `memory.peak` and
  `memory.max` supply the peak and the ceiling. All three are read defensively: a kernel that does not
  expose them degrades to "not measured", never to an error.
- `oom_killed` is deliberately **`None` on the host backend and `False` on the sandboxed one**. The
  distinction is load-bearing: `None` means "this backend cannot tell you", `False` means "we looked
  and it did not happen". Section 12 asserts both, so the UI can never confuse the two.
- `_structured()` sends `actual`/`expected` as JSON so the UI can point at the differing *index*.
  It checks the item count and encoded length *before* serialising, so a 10-million-element list
  cannot make the API encode a value it is about to discard.

#### Three traps, all found by running rather than reading

1. **The sandbox image was stale, and nothing said so.** The image was built at 13:41; the harness was
   edited at 13:49. The result was not an error — the truncated output simply arrived *without* the
   `stdout_truncated` flag, so the UI would have shown a cut-off transcript with no explanation.
   Section 12 caught it incidentally (its bound is read from the harness source, so a stale image
   fails the assertion), and section 11 now guards it directly by comparing the image's build time
   against the newest of the two source files. **This is the same failure mode as a stale uvicorn:
   everything succeeds and behaves like the old version.**
2. **The wall-clock bound was backend-blind.** The 4s ceiling was calibrated on Docker (2.25–2.62s
   warm) and then applied to the host backend, which failed it at 4.66s — correctly, because spawning
   a Windows process per case costs 0.59–1.0s against ~0.26s inside the container. The bounds are now
   per-backend (4s / 8s) with the measured baseline quoted in the message. This is the *same* mistake
   as the original section 5b bug: an assertion calibrated on one thing, applied to another.
3. **The OOM probe must not run on the host backend.** On the host there is no cgroup to stop it, so
   an unbounded-allocation probe would eat the machine's memory rather than fail cleanly. The *run*
   is gated, not just the assertion — a subtle distinction that only matters when you get it wrong.

#### A gap this phase closed in passing

`POST /api/submissions/run` returns a plain `dict` that FastAPI validates against
`response_model=RunResponse`, so a field name drifting between `run_submission` and the schema
produces a **500 that neither `check_runner` nor `tsc` can see** — the runner is correct and the
TypeScript types are hand-written. Section 12 now validates the real payload against the real model,
which needs no server, no token and no database.

**Section 11 is new and permanent:** `RESULT_SENTINEL` is asserted identical across all *three*
files that read or write it (harness, sandbox entrypoint, API) — a drift there makes every submission
report "produced no result" while the runs themselves succeed. `SANDBOX_SENTINEL` is checked
two-way, and the Dockerfile's `COPY` destination is checked against the path the entrypoint actually
looks in.

---

### Phase 4 — JavaScript, and a catalogue worth browsing
- `docker/runner-node/Dockerfile` — `node:22-slim`.
- JS harness + driver generator. Node is the cheapest second language: no compile step, so it
  reuses Phase 2's plumbing unchanged.
- `problems.json` grows from 5 to **12** problems, each with Python and JavaScript starters.
  Deliberately chosen to include real Hard problems — the catalogue is currently four Easy and one
  Medium, which undersells the platform.
- Category filter in the UI (`tags` already exist; `ProblemsPage` filters on difficulty only).

**Exit:** problem 1 in JavaScript reproduces `3/4`; 12 problems browsable and filterable; the
language selector persists per problem.

**DONE 2026-09-23.** `check_runner.py` reports **126 passed / 0 failed / 0 skipped** on `docker`
and **116 / 0 / 4 skipped** on `subprocess` (the four skips are the Docker-only probes, self-skipping
by design); `tsc --noEmit` exit 0; `vite build` clean at 1697 modules. All three exit criteria are
asserted by the suite rather than checked by eye:

| Criterion | Measured |
|---|---|
| problem 1 in JavaScript reproduces `3/4` | `3/4`, failing case `Large input (performance)`, by timeout at `elapsed=3.0081s` — the *same* case and the *same* mechanism as Python, and asserted **through the real HTTP route** as well as through the service layer |
| 12 problems browsable and filterable | 12 problems / 49 test cases, every one offered in Python and JavaScript; `ProblemsPage` filters on difficulty **and** category |
| the language selector persists per problem | `WorkspaceRoute` stores the choice per problem id in `localStorage`; a run is marked `stale` when the language changes, not only the code |

**Section 14 is new and permanent:** it drives the real ASGI app through `POST /api/submissions/run`
with only `current_user` overridden, because every other section reaches the runner through
`run_submission` or calls a route function directly — and neither proves what the browser does. A
field renamed on one side of that boundary is a 500 the student sees while the runner stays perfectly
correct, invisible to every other check and to `tsc`. The route is also asserted to be **genuinely
gated (401) before the override is installed**, so the section cannot quietly become an
unauthenticated test that passes against a broken `current_user`.

The selector itself is a native `<select>` rather than a custom popover: the page already sets
`color-scheme: dark`, so the OS draws a matching option list, and keyboard, focus and screen-reader
support come for free instead of being reimplemented.

#### Two traps found here, both worth remembering

**1. A threshold measured on a loaded machine is not a threshold.** The JavaScript performance case
did not discriminate: at `n = 100,000` the naive JS solution finished in **2.7358s** against a 3s
limit and *passed* — a 10% margin, so the demo only told its story in Python. The `100,000` figure
had been measured during a suite run that took **3m07s instead of 1m37s**, with every problem coming
in ~2× faster, i.e. on a busy machine. Re-measured idle:

| n | JS naive | × limit | JS optimal |
|---|---|---|---|
| 100,000 | 2.64s | 0.9× | 0.020s |
| 150,000 | 5.88s | 2.0× | 0.046s |
| **200,000** | **10.48s** | **3.5×** | **0.063s** |
| 250,000 | 16.40s | 5.5× | 0.067s |

`n` is now **200,000** — a 3.5× margin on the naive solution while leaving the optimal one 47× of
headroom. This is the same trap as the wall-clock bounds, in a new disguise, and it is the second
time this project has paid for it. **Any future change to this number must be re-measured in every
language, on an idle machine.** A larger `n` also enlarges the stdin payload (110 KB → 220 KB), but
that is generated on the host *outside* `compute`, so it does not touch Phase 5.

**2. V8 JITs a tight loop; CPython does not — so the ladder floor is per-language.** The scaling
ladders used to start at `n = 1,000`. In Python that is fine; in JavaScript the naive solution reads
**1.31× / 1.86× per doubling** from 1,000 → 8,000, which looks *sublinear*, because V8 is still
interpreting the inner loop and the resulting JIT speedup nearly cancels the quadratic growth. From
8,000 → 64,000 the same code reads **3.04 / 3.69 / 3.47 / 3.97×**. The ladders now start at
**8,000**, and the linear check is asserted as an upper bound only (`1.42×` per doubling, below
`O(n)`'s 2× because of the same warmup effect).

#### Also fixed here

`smoke_test.py` had **zero** saved-code coverage, so the per-language draft feature had shipped twice
(Phase 2, then this phase's rework) without a single test. It is now section 13 of `check_runner.py`
— nine checks, self-skipping without a database, creating and deleting its own throwaway user. It
proves the *constraint* exists rather than merely that the application logic avoids it: a direct
duplicate insert raises `IntegrityError` on `uq_saved_code_user_problem_language`.

Section 14 also settled a vocabulary question the first time it ran, by failing: the demo run's
`status` is **`partial`**, not `failed`. `_determine_status` reserves `failed` for a run in which
*nothing* passed, so `3/4` is `partial` and the UI colours it amber. The assertion had been written
from memory and the check caught it — which is the argument for asserting the status rather than the
count alone.

---

### Phase 5 — Measured complexity
The current review *asks the model* what the complexity is. That is a claim the system cannot check,
and the plan's own §13 forbids the model from inventing things. So measure it instead.

- **Measured scaling, all languages.** Time the student's own code at two or more input sizes and
  classify the growth from how it responds. Language-agnostic, needs no per-language parser, and it
  is *evidence* rather than an opinion.
  - **Measure `compute`, not `elapsed`.** The harness already returns seconds spent inside the
    student's own code, excluding interpreter startup. This is not optional: measured 2026-09-22, a
    trivial case computes in **19 µs** against **1.09 s** of wall clock, so `elapsed` is 99.998%
    process spawn and would classify every submission as identical.
  - **Never classify from a single doubling.** Measured pairwise ratios for a genuinely linear
    solution came out **2.63, 1.64, 2.74, 1.31** — right on average, but noisy enough that one pair
    reads as ~1.0, because its absolute time is under a millisecond. Compare growth **per doubling**
    across a range wide enough for the signal to clear the jitter, and take the best of several
    runs. Quadratic at the same sizes measured **4.11** and **3.92** per doubling, so the two are
    cleanly separable once the comparison is done this way.
  - Report the measurements alongside the inferred class, and let the model explain them.
- **Python AST detail.** `ast` is in the standard library: loop nesting depth, membership tests
  against a list where a set would do, sorting where counting would do. This is what turns "it looks
  quadratic" into "your inner loop scans a list on every iteration".
- **`services/complexity.py`** owns both, and the measured numbers go into the review prompt with an
  instruction to *explain* them rather than guess. The offline heuristic reviewer gets the same
  numbers, so the no-key path stays consistent with the keyed one.
- `ReviewComplexity` gains `measured_time` / `measured_space` alongside the existing
  `current_*`/`suggested_*` fields, so the UI can show a measured value next to the suggested one.

#### Prerequisites, discovered 2026-09-23

Four things this phase needed that did not exist. **1, 2 and 4 are done**; **3 is the design decision
this phase still has to make.**

**DONE — 1. Every problem now declares how to scale its input.** `app/data/scaling.py` owns a small
spec language and `problems.json` gives each of the twelve problems a `scaling: {"kind": ...}` entry
naming one of ten kinds. A scaling spec is deliberately *not* a test case: it states the shape of an
input of size *n* and carries no expected value, because a measurement only needs the student's code
to run. Several inputs are chosen so that a solution does its **typical** work rather than bailing out
early — Two Sum's target is reachable only from the last two elements, so a quadratic scan cannot find
it on the first pass and measure as if it were constant; Valid Anagram gets two strings that really
are anagrams; Product of Array Except Self gets all ones, because with values of 2 or more the running
product grows to *n* bits and multiplying those is O(n²) in **bit** operations even for the intended
linear solution — a false quadratic signal produced entirely by arithmetic rather than by the
algorithm. `check_runner` section 15 asserts the payload grows with *n* and that each spec builds
exactly the arguments the signature declares.

**DONE — 2. `code_runner.measure_scaling()` is the public ladder.** It runs the whole ladder in **one
container** and returns a `ScalingMeasurement` — raw numbers, deliberately uninterpreted, so the
classification rule can change later without re-running anything. A size that produced no measurement
is `None` and never `0.0`: a zero reads as an infinitely fast solution, which would classify as
constant time — the opposite of the truth for a submission that timed out. `_execute` gained a
keyword-only `budget`, because a ladder is *expected* to be slow at its largest size and
`SUBMISSION_TIMEOUT_SECONDS` would cut it short.

**DONE — 4. Measurement sizes are separate from the performance case.**
`DEFAULT_SIZES = (4_000, 16_000, 64_000)`, plus a separate and longer `SCALING_TIMEOUT_SECONDS` (40s)
backstop. Neither is tuned — see the trap below.

**OPEN — 3. The classification rule must be relative, not absolute.** This is the unmitigated half of
the warning recorded under Phase 2, and it is now the whole of the remaining work. Problem 1's own
*optimal* solution — a hash set, genuinely O(n) — measures **2.54× / 2.68× / 3.15× per doubling
against an ideal 2.0×**, because hash-table growth is allocation-bound and rehashes in steps. Any
classifier using a fixed threshold calls that superlinear, i.e. tells a student their optimal solution
is quadratic. The fix is to measure a known-linear baseline **on the same ladder, in the same
container, in the same run** and classify the student's growth *relative to that*, which also cancels
machine load and JIT state. `measure_scaling` takes `code` as a parameter precisely so a probe can be
passed to it. Getting this wrong is worse than not shipping the feature: a confidently wrong
complexity claim is exactly what plan §13 exists to prevent.

#### A third instance of the same trap, found while building this

**Do not tune these numbers yet.** Measured 2026-09-23 while building items 1 and 2, the *same* code
at the *same* size came in **34× slower** than the recorded ladder — 1.33s against 39ms at n=8,000 —
and an A/B of the two input mechanisms (the old `generate.range` and the new `scaling` kind) agreed to
within 7%, so the input was not the cause. **C: was at 100% full: 86 MB free of 232 GB.** Docker
Desktop and Windows both thrash when the system drive is full.

This is the third time this project has paid for picking a number off a loaded machine, and the first
time the cause was identified rather than only observed. Three consequences, all deliberate:

- `DEFAULT_SIZES` and `SCALING_TIMEOUT_SECONDS` are **configurable and untuned** — a shape, not a
  measurement.
- `measure_scaling` **reports a missing measurement per size instead of inventing one**, and section 15
  **skips** (with the harness' own reason) rather than fails when a ladder cannot complete: a machine
  that cannot finish a ladder is an environment fault, not a code defect.
- The real numbers must be re-measured with **C: clear**, before item 3 picks any threshold.

**Exit:** the nested-loop submission is reported as measured superlinear, with the two measurements
visible in the review; the review cites those numbers rather than a model guess; a Python-only
static finding appears as a separate issue.

---

### Phase 6 — Java and C++
**The expensive phase. Deliberately last, so everything before it is already demonstrable.**

- `docker/runner-java/Dockerfile` — `eclipse-temurin:21-jdk`.
- `docker/runner-cpp/Dockerfile` — `gcc:14`.
- Both need a **compile step**, which introduces a new error type: **Compilation Error**, with the
  compiler's first diagnostic line surfaced and the rest available. `RunError.type` gains `compile`;
  `RunStatus` gains nothing — a compile failure is `error`.
- Driver generation from the declared signature: a `Main.java` / `main.cpp` that includes the
  student's file and calls the entrypoint with native literals.
- Return-value serialisation helpers per language (int, double, bool, string, array, list).
- Then backfill all 12 problems with Java and C++ starters, taking the catalogue to **12 problems ×
  4 languages = 48 starter snippets** and 48 signatures. This is content work, and it is the real
  cost of the four-language decision — budget it accordingly.

**Exit:** problem 1 in Java and in C++; a deliberate compile error produces the friendly
Compilation Error card rather than a 500 or a raw `javac` dump.

---

### Phase 7 — Hardening, tests, docs
- **`pytest` for the backend.** There is currently no test framework in this project at all — only
  two hand-rolled scripts that need live servers. Four language harnesses, a driver generator, a
  comparator, and a measured-complexity classifier cannot be maintained by a smoke script. Tests for
  the comparator and driver generator run with no Docker and no network.
- **Per-user rate limit on `/api/reviews`.** The Gemini free tier allows 5 requests per minute;
  nothing currently throttles it, so three people clicking during a demo will hit 429. A simple
  in-process token bucket keyed on the Clerk `sub` is enough — no Redis.
- **Rewrite `README.md`.** It still claims "no database, no auth", lists two pages, and omits
  `/api/auth/me`, `/api/progress`, `/api/submissions` and `/api/saved-code` from its API table.
- **Retire the stale plan sections.** The old `plan.md` §20/§21 promise a demo that works without
  logging in, which stopped being true in Phase 2. This document replaces them.
- **Rename the Clerk application** — the sign-in card still reads "Sign in to My Application". A
  dashboard change, not code.

**Exit:** `pytest` green with no Docker required for the pure-logic tests; a 6th review request
inside a minute is refused with friendly copy instead of a provider error; README matches reality.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **C: fills up again** | Blocks all Docker work. Already broke tooling twice. | **Phase 0 done 2026-09-22** — Docker's disk image now lives at `E:\Docker\DockerDesktopWSL\` and C: is back to 3.6 GB free. Keep an eye on it: four toolchain images will want 3–5 GB, and they will land on E: with the image. |
| **Docker Desktop on Windows is unreliable** | A demo that cannot run. | `RUNNER_BACKEND=subprocess` fallback for Python; health reports the state; the UI says so. |
| **Four-language content cost** | 48 starters + 48 signatures, all of which must be correct or *every* submission errors. | Do it in two waves (Python+JS at 12 problems, then Java+C++), and let the per-language starter-code assertion in the smoke test catch signature drift. |
| **The keystone refactor regresses the demo** | The headline `3/4` becomes something else and the demo stops telling its story. | Phase 1's exit criterion is that exact number, on the old runner, before Docker is involved — and `scripts/check_runner.py` asserts it offline, with no server, token or quota. |
| **Container lifecycle costs ~2s per submission on Windows** | Every run feels slow, and the pre-Phase-2 "under 2s" target is missed by ~0.3s warm. | Accepted and measured (Phase 2). One container per submission, not per case, so the cost is paid once. `compute` is reported separately from `elapsed` so the *student's* code is judged on its own time. Phase 6 needs the container anyway for the compiler toolchains. |
| **Measured complexity misclassifies** | A confident wrong answer in the review. | Report the measurements and the inferred class as a range, and let the model explain rather than assert. **Measured 2026-09-22: the margin is real but not large, and the benchmark matters more than expected** — a hash-set solution read 2.54–3.15x per doubling against an ideal 2.0x, while a plain scan read 1.93x and the nested loop 4.09–4.11x. Phase 5 pairs the timing with a static read of the code, and section 5b of `check_runner.py` asserts the separation instead of assuming it. |
| **The sandbox image is stale relative to the harness** | Silent, and the worst kind: every run succeeds and behaves like the *old* harness, so a fix appears not to have worked. Bit once already — an image built at 13:41 ran a harness edited at 13:49, and truncated output arrived with no `stdout_truncated` flag. | `check_runner.py` section 11 compares the image's build time against the newest of the two source files and fails with the exact rebuild command. Section 12's output bound is read from the harness *source*, so a stale image also fails there. Same discipline as restarting uvicorn by hand rather than trusting `--reload`. |

---

## 7. Your open items

1. **Phase 0, the disk — DONE 2026-09-22.** Docker's disk image moved to `E:\Docker\DockerDesktopWSL\`,
   the daemon starts, and `check_runner.py` passes 69/0 against the sandbox.
2. **The ~10 GB reclaim** under your user profile — I need explicit per-item confirmation before
   touching any of it.
3. **The Clerk application rename** (`My Application` → `CodeReviewer`) — dashboard only.
4. **`plan.md` location.** This document is at the repo root and version-controlled. The original
   MVP plan in `Downloads` is untouched, and is now historical. Say the word if you want it
   replaced or moved instead.
5. **Unpushed commits.** `9888f37` and `28a8064` are still local. Origin is a separate decision and
   has not been asked for.
6. **Nothing is committed since `28a8064`.** Phases 1–3 are **17 modified files** (+2,063 / −539) and
   **6 untracked paths**, all still in the working tree. Explicit staging is the house rule, so say
   when you want the commit — the `package-lock.json` churn rides along with it, as agreed.

   Worth knowing before that commit: the untracked set is not incidental. It contains **`docker/`**
   (the whole sandbox — Dockerfile and entrypoint), **`backend/app/data/problems.json`** and
   **`test_cases.json`** (the entire catalogue, without which the app serves nothing),
   **`plan.md`**, **`.dockerignore`** and **`scripts/check_runner.py`**. I checked: none of them are
   gitignored, so a plain `git add -A` picks them all up — there is no silent exclusion to work
   around. But until they are committed, the sandbox, the problem data and this plan exist only on
   this disk.

---

## 8. Definition of done

The full demo is complete when, on a machine with Docker running, a signed-in student can:

1. Browse a catalogue of 12 problems, filter it by difficulty and category, and search it.
2. Pick a problem and choose any of **Python, JavaScript, Java or C++**.
3. Write code in Monaco with syntax highlighting for that language.
4. Run it against real test cases **inside a network-isolated container**, with per-case timing and
   their own `print` output visible.
5. Get an error they can act on — syntax, compile, runtime or timeout — in language-appropriate
   copy, without the page ever breaking.
6. Request an AI review that cites **measured** performance numbers, names the specific construct
   causing the problem, and offers a hint before the full approach.
7. See that run and review in their history, and their progress on the dashboard.

And it must all still work when the LLM key is absent (rule-based reviewer) and, for Python, when
Docker is down.
