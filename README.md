# CodeReviewer

A web-based AI-powered coding practice and code review platform.

Pick a problem → write Python → run it against real test cases → get an
educational review from an AI mentor.

```
PROBLEM → CODE → RUN → TEST RESULTS → AI REVIEW → IMPROVEMENT
```

This is the **full-demo** build described in [`plan.md`](plan.md). That plan
supersedes the original one-week MVP plan: the MVP's "no database, no auth,
Python only" constraints are historical, and the current scope is four
languages running in a Docker sandbox. See `plan.md` for the phase list and
what is actually built.

> **Where the build is right now:** phases 0–4 are done. **Python and
> JavaScript** both execute inside the **Docker sandbox** — one image per
> language, `RUNNER_BACKEND=docker` is the default and `subprocess` is an
> explicit fallback that trades isolation for speed. Runs report per-case
> timing, captured `print` output and sandbox metadata, and the catalogue is
> **12 problems across two languages**, filterable by difficulty and category.
> Measured complexity is phase 5, Java and C++ phase 6. `plan.md` has the
> detail.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript + Vite, Monaco Editor, plain CSS |
| Backend | Python + FastAPI + Uvicorn |
| AI | Google Gemini (REST) with a Groq fallback, behind a swappable service module |
| Data | PostgreSQL for users, runs, reviews and drafts; JSON for the problem catalogue |
| Auth | Clerk (token verification only — no passwords stored here) |
| Execution | One subprocess per test case, with per-case timeouts |

---

## Layout

```
.
├── frontend/
│   ├── src/
│   │   ├── components/     # Header, ProblemCard, ProblemPanel, EditorPanel,
│   │   │                   # TestResults, ReviewPanel, LandingHero,
│   │   │                   # BeamsBackground, RequireAuth, AuthTokenBridge
│   │   ├── pages/          # Home, Problems, Workspace, History, Submission,
│   │   │                   # Profile, SignIn, SignUp, NotFound (+ *Route wrappers)
│   │   ├── services/       # api.ts — the only module that speaks HTTP
│   │   ├── types/          # mirrors the backend Pydantic schemas
│   │   ├── App.tsx         # layout + routes
│   │   └── styles.css
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI app, CORS, startup diagnostics, health
│   │   ├── config.py       # env-driven settings
│   │   ├── db.py           # the only module that reaches Postgres
│   │   ├── deps.py         # Clerk token verification
│   │   ├── models/         # user, submission, review, saved_code
│   │   ├── routes/         # problems, submissions, reviews, progress,
│   │   │                   # saved_code, auth
│   │   ├── services/       # code_runner.py, ai_reviewer.py, _runner_harness.py
│   │   ├── data/           # problems.json, test_cases.json (+ loaders)
│   │   └── schemas/        # submission.py, saved_code.py, user.py
│   ├── alembic/            # migrations
│   ├── scripts/            # smoke_test.py, check_runner.py, check_retry_policy.py
│   ├── requirements.txt
│   └── .env.example
│
├── plan.md                 # the full-demo plan — source of truth
└── README.md
```

---

## Running it

You need **two terminals**: one for the backend, one for the frontend.

### 1. Backend

```bash
cd backend

# first time only - create the virtual environment
python -m venv .venv

# Windows
.venv/Scripts/python.exe -m pip install -r requirements.txt
# macOS / Linux
# .venv/bin/python -m pip install -r requirements.txt

cp .env.example .env      # then fill in the values below
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health

> Restart the backend explicitly after editing code. Do not rely on
> `--reload` — it has been observed picking up one edited file out of four,
> which leaves a server that answers every request with the *old* behaviour.
> That is the most confusing failure mode in this project.

### 1b. The execution sandbox

Student code runs in a container, not on this machine. There is **one image per
language** — `codereviewer-runner-python` (`python:3.12-slim`) and
`codereviewer-runner-node` (`node:22-slim`). Two images rather than one combined
image on purpose: the container *is* the security boundary, so an image that
carried both runtimes would let a Python submission reach Node. Each holds a
base runtime, a supervisor entrypoint and a harness, and nothing else.

Build both **from the repository root** — the build context needs both the
Dockerfiles and the shared Python harness:

```bash
docker build -f docker/runner-python/Dockerfile -t codereviewer-runner-python .
docker build -f docker/runner-node/Dockerfile   -t codereviewer-runner-node   .
```

The container gets no network, one CPU, a 512m memory ceiling, a 128-process
limit, a read-only filesystem, a size-capped tmpfs for the one writable
directory, and no Linux capabilities. Test cases run as separate child
processes *inside* it, so one slow case is killed without losing the rest.

Runs report what the **sandbox** did as well as what the code did: the child's
exit code or the signal that killed it, whether the cgroup's OOM killer fired
(attributed to the exact case, read from the kernel's own monotonic counter
rather than guessed from a `SIGKILL`), peak memory against the ceiling, and
student `print` output capped at 4,000 characters with an explicit "truncated"
marker instead of an unbounded buffer. On the host backend these fields are
`null` — "this backend cannot tell you" is deliberately distinct from "we
looked and it did not happen".

**The image bakes in a copy of its harness.** If you edit
`backend/app/services/_runner_harness.py`, `docker/runner-node/harness.js`, or
either `entrypoint.py` / `entrypoint.js`, you must rebuild that image, or every
run keeps using the old code — silently, because the old code still works.
`check_runner.py` compares each image's build time against the sources it runs
and fails with the exact rebuild command if the image is older.

Two costs worth knowing before you change anything here:

- **A container costs ~2s to create and destroy on Windows.** That is paid
  once per submission, not per test case. It is the price of the sandbox.
- **The per-case `compute` is measured inside the container**, not around it.
  See the note on `compute` vs `elapsed` under [API](#api).

If Docker is not available, `RUNNER_BACKEND=subprocess` in `backend/.env` runs
student code directly on this machine with **no isolation**. That is a
deliberate, explicit choice — the app never downgrades on its own. With
`RUNNER_BACKEND=docker` and a stopped daemon, runs fail loudly and
`/api/health` reports `docker_ok: false`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### 3. Configuration

`backend/.env` needs three things. Each degrades honestly rather than
crashing, and `/api/health` reports the state of all three.

| Variable | Without it |
|---|---|
| `DATABASE_URL` | Nothing can be saved; `/api/health` reports `database_ok: false` |
| `CLERK_SECRET_KEY` | Nobody can sign in; authenticated routes answer 503, not 401 |
| `GEMINI_API_KEY` | Reviews come from the built-in rule-based reviewer |

**AI review is optional.** With no key, `ai_reviewer.py` uses a deterministic
rule-based reviewer so the whole workflow still runs — it just cannot reason
as freely as a model, and the header shows an "Offline review" badge. Get a
free Gemini key at https://aistudio.google.com/apikey. `GROQ_API_KEY` is an
optional fallback used only after Gemini exhausts its own retries.

---

## Checking it

Three scripts live in `backend/scripts/`. None needs a test framework.

### Offline — no server, no token, no quota

```bash
cd backend
.venv/Scripts/python.exe scripts/check_runner.py
```

Imports the real runner and catalogue and exercises them directly: every
problem's reference solution must pass, the demo problem must score exactly
`3/4` with the nested-loop solution, the large-input case must be real (not
silently empty), per-case timing and captured stdout must come back, and the
comparison and language-refusal rules must behave. **This is the fastest way
to answer "did I just break the runner?"**

It runs in fifteen numbered sections and needs no server, token, quota or test
framework. Six are worth knowing about by name:

- **Section 10** proves the sandbox actually isolates: student code cannot reach
  the network, a runaway allocation is stopped and told *why*, an infinite loop
  is killed at the per-case timeout without losing the other cases, and no
  container outlives its request.
- **Section 11** asserts the sentinel literals match across all five files that
  read or write them, that each Dockerfile installs its harness where that
  sandbox looks for it, and that each image is newer than the source it was built
  from.
- **Section 12** asserts the execution-feedback guarantees: 10,000 printed lines
  come back bounded *and flagged as truncated*, a wrong answer arrives as two
  structured values the UI can diff, an out-of-memory case reports
  `oom_killed: true` with the peak that reached the ceiling, and the payload
  validates against the same response model FastAPI enforces.
- **Section 13** covers the saved drafts, which nothing else tested. It creates
  and deletes its own throwaway user, and proves the per-language unique
  constraint exists by attempting a duplicate insert rather than trusting the
  application logic to avoid one.
- **Section 14** drives the real ASGI app through `POST /api/submissions/run`
  with only `current_user` overridden — the boundary the browser actually uses,
  where a field renamed on one side is a 500 that no other section would see. It
  also proves the route is genuinely gated before overriding it, so it cannot
  quietly become an unauthenticated test that passes against a broken gate.
- **Section 15** checks that measured complexity has something to measure: every
  problem declares how to build an input of size *n*, the generated payload
  really grows with *n*, each spec builds exactly the arguments its signature
  declares, the spec never reaches the API, and every problem's reference
  solution runs on its own generated ladder — one container each. It does
  **not** assert a complexity classification; that is a later phase's job, and
  the margin it would need cannot be chosen on a loaded machine.

Sections 10 and the OOM half of 12 self-skip under `RUNNER_BACKEND=subprocess`,
where there is no sandbox to probe — and the OOM probe in particular *must* skip
there, since on the host there is no cgroup to stop it.

**Timings are reported, structure is asserted.** Section 3 counts docker
invocations by patching `subprocess.run` and requires **exactly one `docker run`
per submission** — a container per case would be four calls and four times the
lifecycle cost for no extra isolation. That is asserted because it is
load-independent; wall-clock bounds are not. Two absolute timing bounds were
written and both had to be withdrawn the same day: the same submission measured
2.25–2.62s once and 3.87–8.17s later with nothing changed, so a tight bound only
teaches you to ignore failures. What remains is a loose catastrophic-slowness
guard.

```bash
.venv/Scripts/python.exe scripts/check_retry_policy.py
```

Replays real captured Gemini and Groq error bodies through the retry logic and
asserts that a transient `503` backs off and retries, a `429` stating a long
wait fails fast instead of hanging the request, a `400` is never retried, and
a Gemini failure reaches Groq while a Gemini *success* never touches it.

### Before a demo — with both servers running

```bash
cd backend
.venv/Scripts/python.exe scripts/smoke_test.py --token "<clerk session token>"
```

Walks every endpoint the UI calls, in order, and prints a pass/fail line for
each: service identity, the catalogue, the per-language starter-code contract,
code execution (including the `3/4` partial demo case), captured stdout and
per-case timing, language refusals, the AI review, and error handling.

**`--token` is required for the execution and review sections.** Sign-in
became mandatory in Phase 2, so `POST /api/submissions/run` and
`POST /api/reviews` answer `401` to an anonymous caller. Grab the token from
the browser's devtools (Application → Cookies → `__session`) or set
`SMOKE_TOKEN`. Without it those sections are skipped with a warning rather
than reported as failures.

`--no-review` skips the review section — the only part that spends API quota.
`--base-url` points it at a different port.

The starter-code check runs **every problem in every language it declares**
and asserts the starter produces `failed` rather than `error`. An `error`
there means an entrypoint name has drifted away from its starter signature,
which would otherwise show up as *every* submission erroring.

> A `WARN` in the smoke test's review section is usually the provider rather
> than a bug: the Gemini free tier allows 5 requests per minute, and the flash
> models intermittently return `503 high demand` or time out. If Groq is
> configured the fallback absorbs most of this, and the run reports
> `source=groq` for the affected reviews.

---

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | Readiness: LLM, database, Clerk |
| `GET` | `/api/problems` | — | List all problems |
| `GET` | `/api/problems/{id}` | — | One problem, with per-language starter code |
| `POST` | `/api/submissions/run` | ✔ | Execute code against the test cases |
| `GET` | `/api/submissions` | ✔ | Your run history, newest first |
| `GET` | `/api/submissions/{id}` | ✔ | One recorded run, with its review |
| `POST` | `/api/reviews` | ✔ | Produce a structured AI review |
| `GET` | `/api/progress` | ✔ | Per-problem progress across the catalogue |
| `GET` | `/api/saved-code/{problem_id}` | ✔ | Your saved draft (null when none) |
| `PUT` | `/api/saved-code/{problem_id}` | ✔ | Replace your saved draft |
| `GET` | `/api/auth/me` | ✔ | The signed-in user |

Run statuses: `passed` · `partial` · `failed` · `error` · `timeout`

### What a run reports per test case

`POST /api/submissions/run` returns one entry per case carrying both what the
code did and what the sandbox did:

| Field | Meaning |
|---|---|
| `elapsed` | Wall clock for the case, **including** process startup and container overhead |
| `compute` | Seconds spent **inside the student's own code**, excluding interpreter startup |
| `stdout` | What the student printed, capped at 4,000 characters |
| `stdout_truncated` | `true` when that cap was hit, so the UI can explain the cut |
| `actual` / `expected` | `repr`s, always present — the fallback for values JSON cannot carry |
| `actual_value` / `expected_value` | The same values as real JSON, so the UI can point at the differing *index*. `null` when too large or not representable |
| `exit_code` / `signal` | How the child ended. A clean exit sets the first, a killed child the second — never both |
| `oom_killed` | From the container's own cgroup counter. `null` on the host backend, `false` on the sandboxed one — "cannot tell you" is not "did not happen" |

A top-level `sandbox` object carries the submission's memory ceiling, peak
memory and OOM flag; it is `null` for the host backend, which has no container
and therefore no ceiling to report.

### `compute` vs `elapsed`, and why both exist

They measure different things and only one of them is about the student.

`elapsed` is wall clock. On Windows, spawning a process costs 0.59–1.0s and
creating a container costs another ~2s, against roughly 20µs of actual work for
a trivial case — so `elapsed` is dominated by *our* overhead, not theirs.

`compute` is measured inside the child, from executing the module to getting the
answer. A function that ignores its input entirely stays flat at 1.26× across
16× the input, which is how we know it is not just measuring interpreter boot.

That distinction is what makes Phase 5's complexity analysis possible at all:
comparing `compute` across two input sizes measures the algorithm, whereas
comparing `elapsed` would mostly measure process startup. The two are surfaced
separately in the UI so a student sees honest numbers for both.

---

## Problems

| # | Title | Difficulty | Cases |
|---|---|---|---|
| 1 | Contains Duplicate | Easy | 4 |
| 2 | Two Sum | Easy | 3 |
| 3 | Valid Anagram | Easy | 3 |
| 4 | Binary Search | Easy | 3 |
| 5 | Maximum Subarray | Medium | 3 |
| 6 | Valid Parentheses | Easy | 7 |
| 7 | Group Anagrams | Medium | 3 |
| 8 | Product of Array Except Self | Medium | 4 |
| 9 | Merge Intervals | Medium | 5 |
| 10 | Longest Substring Without Repeating Characters | Medium | 5 |
| 11 | Trapping Rain Water | Hard | 4 |
| 12 | Median of Two Sorted Arrays | Hard | 5 |

**12 problems, 49 test cases, every one offered in Python and JavaScript.** The
catalogue is browsable and filterable by **difficulty** and by **category**
(`tags`); the language you pick is remembered per problem.

Problem 1 additionally has a **large-input performance case** (200,000
elements, 3s limit). A nested-loop solution passes the three correctness cases
but exceeds the limit on that one, which is what produces the demo's
`3/4 tests passed` — and gives the AI reviewer something concrete to explain.
It is deliberately the *same* result in both languages; see below.

The size is chosen so the case bites in **every** supported language, not just
the slowest one. V8 JITs a tight loop where CPython does not, so the naive
solution is roughly 3x faster in JavaScript; at 100,000 elements it finished in
2.64s against the 3s limit and passed, and the demo only worked in Python. At
200,000 it needs 10.48s, while the optimal solution stays at 0.06s.

### Test case format

Test cases live in `backend/app/data/test_cases.json`, keyed by problem id.
They are **JSON, not Python**, because the same case has to be runnable from
Python, JavaScript, Java and C++:

```json
{
  "name": "Basic duplicate",
  "args": [[1, 2, 3, 1]],
  "expected": true
}
```

- `args` — the positional arguments of the call. `[[1, 2, 3, 1]]` is executed
  as `entrypoint([1, 2, 3, 1])`.
- `expected` — the expected return value, as JSON. Compared by the **runner**,
  not by the language harness, so the tolerance rules exist once instead of
  once per language.
- `generate` — an alternative to `args` for inputs too large to write out.
  `{"kind": "range", "n": 200000}` expands to one positional argument holding
  the integers 0..199999. This is what replaced the Python-only
  `list(range(200000))` and is why the performance case works in every language.
- `timeout` — per-case override in seconds.
- `comparator` — optional; `exact` (default) or `unordered`.

### Adding a problem

Add an entry to `backend/app/data/problems.json` with a `languages` map and a
`scaling` spec, add its cases to `test_cases.json`, then run `check_runner.py` —
it validates both files and will tell you what is missing. A language absent
from a problem's `languages` map is one that problem cannot be attempted in,
which is what lets the catalogue grow language by language.

The `scaling` spec says how to build an **input of size *n***, so the reviewer
can time a submission at several sizes and measure how it grows. It names one of
the kinds in `backend/app/data/scaling.py`, and carries no expected value at all
— a measurement only needs the student's code to *run*, never to be right. A
problem with no `scaling` spec still works; it simply cannot have its complexity
measured, and `check_runner` reports that rather than treating it as an error.
