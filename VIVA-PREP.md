# CodeReviewer — viva / demo questions

Prepared from the actual source in this repository. Every number below is either read out of the
code or was measured on this machine; where a figure is *not* trustworthy, it says so.

**Read this first.** The strongest thing you have is not the feature list — it is that this project
has been *measured* and *verified*, and that you can say plainly what does not work yet. Teachers
probe for the second thing. Almost every "hard" question below is really asking *"do you know the
limits of what you built?"* Answer those honestly and you are in good shape.

---

## The 60-second version

> CodeReviewer is a local, single-machine coding-practice platform. A student picks one of 12
> problems, writes a solution in Python or JavaScript in a browser editor, runs it against real
> test cases, and gets a structured AI review.
>
> The part that makes it interesting is that **student code never runs on the host**. Each
> submission gets its own hardened Docker container — no network, 512 MB, one CPU, read-only
> filesystem, nobody user — and each test case gets its own child process inside it, so one slow
> case is killed without losing the others.
>
> The other decision worth stating is that **comparison happens outside the sandbox**. The
> container is told the arguments but never the expected answers, so student code cannot read the
> answer it is being tested against, and the tolerance rules exist in one place instead of once per
> language.

That is the whole project. Everything else is detail hanging off those two sentences.

---

## A. Project framing

**A1. What problem does this solve, and who is it for?**
A student learning to code gets two things from a practice platform: *did it work* (tests) and
*why is it not good* (review). Most platforms give the first and stop. This one is built around the
second — the golden rule of the project is the workflow
`PROBLEM → CODE → RUN → TEST RESULTS → AI REVIEW → IMPROVEMENT`, and every phase had to leave that
path working end to end.

**A2. Why not just use LeetCode / HackerRank?**
Those are judge-first: you get pass/fail and a leaderboard. This is mentor-first. The review is the
product — it names the construct in *your* code that caused the problem ("your nested for loops")
rather than telling you the optimal solution exists.

**A3. What was the scope decision you had to defend?**
Three, and they are all in `plan.md` §1:
- **Local, feature-complete** — no hosting, no deployment, no CI, no production auth instance. The
  target is a demo that runs on one machine, not a service.
- **Four languages** (Python, JS, Java, C++) — expensive, because every problem needs a starter and
  a signature in each, but it is what makes the execution architecture worth building.
- **Instructor view explicitly out of scope** — considered, not selected.

**A4. What is *not* built yet?**
Be upfront: **Java and C++ are not implemented** — they are Phase 6. What exists is Python and
JavaScript, both inside the sandbox. Measured complexity (Phase 5) is partly built: the measurement
ladder exists and every problem declares how to scale its input, but the *classification rule* is
still open. There is also no `pytest` suite — the tests are three purpose-built scripts.

**A5. What would you do differently with more time?**
The order is deliberate and I would keep it. What I would change is the *content* work: 12 problems
× 4 languages = 48 starters and 48 signatures, all of which must be correct or every submission in
that language errors. That is the real cost of the four-language decision, and I under-budgeted it.

---

## B. Architecture and request flow

**B1. Walk me through what happens when a student clicks Run.**
1. Browser `POST /api/submissions/run` with `{problem_id, language, code}` — the only module that
   speaks HTTP is `frontend/src/services/api.ts`.
2. `routes/submissions.py` looks the problem up, calls `resolve_language` and turns its refusal
   into a 400.
3. `code_runner.run_submission()` expands the test cases' arguments, then dispatches to the
   configured backend.
4. The Docker backend starts **one** container for the whole submission with the hardening flags.
5. Inside it, `entrypoint.py` spawns one child process per test case and prints one
   sentinel-prefixed JSON line per case.
6. The Python parent parses those lines, compares against `expected`, and shapes the response.
7. The run is written to Postgres and the row id comes back as `submission_id`.

**B2. Why is the app only two processes plus Postgres plus Docker?**
Because a message queue is a solution to a problem this project does not have. It is a single-user
academic demo. Redis, Celery and a task queue were explicitly ruled out in `plan.md` §1 — they
would add a moving part to the demo path and buy nothing.

**B3. Where are the seams in the codebase?**
This is worth memorising, because "how would you swap X" is the classic follow-up:
- `frontend/src/services/api.ts` — the **only** module that makes HTTP calls.
- `frontend/src/types/index.ts` — mirrors `backend/app/schemas/submission.py`.
- `app/services/ai_reviewer.py`, `_call_llm()` — the only provider-specific code.
- `app/services/code_runner.py` — the only module that knows how code gets executed.
- `app/db.py` — the only module that reaches Postgres.
- `app/deps.py` — the only place a Clerk token is verified.

**B4. How would you add a third language?**
Add a Dockerfile, a harness and a driver generator, then register it in `SUPPORTED_LANGUAGES` and
the `RUNNER_IMAGES` map. Nothing else changes, because comparison, timing and status vocabulary all
live in the parent. That was the entire point of the Phase 1 refactor.

**B5. How would you swap Gemini for OpenAI?**
One function. `_call_gemini` and `_call_groq` already share `_request_with_retries` and differ only
in URL, headers, payload shape and how text is pulled back out — so a third provider is a new
extractor plus a new `_call_*`, and `_call_llm` decides the order.

---

## C. The execution sandbox — expect most questions here

**C1. Why does student code run in a container at all?**
Because it is untrusted code from an untrusted source, executed on a machine that holds API keys.
Without isolation, `import os; print(os.environ["GEMINI_API_KEY"])` works. That is not hypothetical
— the host backend literally strips the environment down to an allow-list for exactly this reason.

**C2. What are the hardening flags, and what does each one stop?**
```
--network none          the code cannot exfiltrate keys or hang on a network call
--memory 512m --memory-swap 512m    it cannot swap the host to death
--cpus 1                a busy loop cannot starve the API server
--pids-limit 128        a fork bomb cannot exhaust the host process table
--read-only             the filesystem cannot be modified
--tmpfs /work:rw,nosuid,size=128m   exactly one writable place, size-capped
--user 65534:65534      runs as nobody
--cap-drop ALL          no Linux capabilities
--security-opt no-new-privileges    and no way to acquire any
```
If they ask "which one matters most" — `--network none`. It is the one that protects the secrets.

**C3. One container per submission, or one per test case?**
Per **submission**. The container is the isolation boundary; the child processes inside it are what
give per-case timeouts and crash isolation. A container per case would pay ~2s of startup four
times over for no extra safety. This is asserted, not asserted-by-eye: `check_runner.py` section 3
patches `subprocess.run` and requires **exactly one `docker run` per submission**.

**C4. Why is `/work` not mounted `noexec`?**
Because Java and C++ have to compile a binary there and run it. `nosuid` stays. That is a real
constraint that shapes the design — you cannot have both "no exec" and "compiled languages".

**C5. How does a runaway `print` loop not get reported as out of memory?**
Because `io.StringIO` was replaced with `_CappedBuffer`. The old behaviour accumulated every byte,
exhausted the 512 MB ceiling, and reported the student's mistake as an OOM — true, and useless. The
cap is **4,000 characters**, applied *on write*, so memory stays flat regardless of volume, and the
result carries a `stdout_truncated: true` flag so the UI can explain the cut instead of showing a
silent ellipsis.

**C6. How do you know a case was killed by the OOM killer and not by something else?**
Read the cgroup's own `memory.events` counter before and after each case. A bare `SIGKILL` is
genuinely ambiguous — the cgroup OOM killer and an external `docker kill` look identical from the
child's return code. The counter is monotonic, so reading it around a case *attributes* the kill to
that case rather than inferring it. `memory.peak` and `memory.max` give the peak and the ceiling.
All three are read defensively: a kernel that does not expose them degrades to "not measured",
never to an error.

**C7. `oom_killed` is `None` on one backend and `False` on the other. Why?**
Because `None` and `False` are different claims. `None` means *"this backend cannot tell you"* — the
host runner has no cgroup. `False` means *"we looked and it did not happen"*. Collapsing them would
let the UI state a fact it does not have.

**C8. What happens if Docker is not running?**
The run fails **loudly**. `/api/health` reports `docker_ok: false`, startup logs an error naming the
cause, and the error message tells the operator to start Docker Desktop or set
`RUNNER_BACKEND=subprocess`. The app never downgrades on its own — a silent switch from "sandboxed"
to "running student code on the host" is a security-relevant change nobody would notice.

**C9. So why does the subprocess backend exist at all?**
Because Docker Desktop on Windows is the least reliable component in this stack, and a demo that
cannot run at all is worse than a demo without a sandbox. It is an **explicit** escape hatch, never
automatic, and only Python has a guaranteed host toolchain — the other languages do not fall back.

**C10. Two images, not one. Why?**
Because the container *is* the security boundary. One image carrying both runtimes would let a
Python submission reach Node. Each image holds a base runtime, an entrypoint and a harness, and
nothing else.

**C11. `subprocess.run(timeout=...)` kills the docker CLI, not the container. Does that matter?**
Yes — it leaks a running container holding its full 512 MB. The fix is three things together:
`--rm`, a unique `--name`, and a `finally` block that force-removes it on every path including the
timeout. `check_runner.py` section 10 checks for leftover containers after every run.

**C12. Why is there a container-level budget as well as a per-case one?**
Per-case limits alone let 12 cases × 3s exceed the host's backstop, at which point the host kills
the container and **every case that had not started is lost**. So `entrypoint.py` enforces
`SUBMISSION_TIMEOUT_SECONDS` itself and reports the remaining cases honestly. The host backstop is
only for a container that hangs outright.

**C13. Where is the sandbox's biggest weakness?**
Honestly: it is Docker Desktop on Windows, and the wall-clock cost. A container costs roughly 2s to
create and destroy, so a submission is **~4–5s** end to end. That is the price of the sandbox, paid
once per submission. On a small problem the unsandboxed host runner is actually *faster* — but it
loses outright the moment a compiler is involved, which is Phase 6.

---

## D. The test-case contract

**D1. Why did test cases have to change format?**
The original format was a Python expression: `{"input": "[1, 2, 3, 1]", "expected": "True"}`. That
is not valid JavaScript, Java or C++, and `"list(range(20000))"` is Python and nothing else. It
could not generalise, so it was replaced **before** a second language existed — while the project
was still Python-only and therefore provable.

**D2. What does a test case look like now?**
```json
{ "name": "Basic duplicate", "args": [[1, 2, 3, 1]], "expected": true, "comparator": "exact" }
```
`args` is a JSON array of positional arguments; `expected` is JSON; `comparator` is optional
(`exact` default, `unordered` where element order is not part of the contract).

**D3. How do you test a 200,000-element input without writing a 200,000-element literal?**
A `generate` spec — `{"kind": "range", "n": 200000}` — tells the harness to build the input itself.
The parent expands it, so every language receives the same concrete values. This is what replaced
the Python-only `list(range(...))`.

**D4. Why are the arguments serialised as native literals rather than JSON-parsed in the container?**
Because that would mean writing a JSON parser in Java and C++. The driver is generated per problem,
per language, per case, so `args: [[1,2,3,1]]` becomes `int[] nums = new int[]{1,2,3,1};` in Java and
`vector<int> nums{1,2,3,1};` in C++. Only a small JSON *serialiser* for the return value is needed
container-side.

**D5. Where does the problem catalogue live, and why not in the database?**
`backend/app/data/problems.json` and `test_cases.json`. Moving it into Postgres was considered and
rejected for this pass: it is read-only reference data, it is version-controlled as JSON, and a
problem can be added without touching Python or running a migration. The cost is that
`submissions.problem_id` is *not* a foreign key — so a stored run whose problem has left the
catalogue falls back to `"Problem 7"` rather than breaking the history list.

---

## E. Comparison, statuses, errors

**E1. Where does the expected answer get compared?**
In the Python parent, in `code_runner`. Never in the container. Two reasons: student code cannot
read the answer out of its own process, and the tolerance rules exist **once** instead of once per
language. The harness answers only "what did this return, and how long did the student's own code
take?"

**E2. What does `_values_match` tolerate, and why?**
Three things, all chosen for a teaching context: exact equality first; `(0, 1)` versus `[0, 1]`
(tuples and lists are the same answer); and `4.0` versus `4`. It deliberately does **not** break
`True == 1` — Python's own rule — because for a problem whose answer is boolean, returning `1` is a
real answer and failing it would teach the wrong lesson.

**E3. What are the run statuses and what does each mean?**
`passed` · `partial` · `failed` · `error` · `timeout`. The non-obvious one: **`failed` is reserved
for a run where nothing passed and nothing raised** — i.e. every case returned a wrong answer. The
demo run scores `3/4`, which is **`partial`**, not `failed`, and the UI colours it amber. An
earlier version of this assertion was written from memory and the test suite caught it.

**E4. What is the demo's headline number?**
Problem 1 (Contains Duplicate) with a nested-loop solution scores **3 of 4 tests passed**. It passes
the three correctness cases and fails only the large-input performance case, by timeout at ~3s. The
same result in Python and in JavaScript — deliberately, because a demo that only tells its story in
one language is not a demo of a multi-language platform.

**E5. What does a student see when their code does not compile?**
For Python, a syntax error is caught *before* execution by `compile()`, so it fails fast and once
rather than four times. For JavaScript there is no in-process parser, so the harness reports it —
one subprocess instead of an in-process parse. The `language` guard on `check_syntax` is
load-bearing: it used to be called unconditionally, which was harmless while Python was the only
language and would have made **every JavaScript submission report a Python syntax error** the
moment a second language existed.

---

## F. The AI review

**F1. How do you stop the model inventing things?**
Three layers. The prompt contains an explicit rule — "never invent test results, and never claim
the code is correct if the test results indicate otherwise" — plus a requirement to cite the
student's actual constructs. The response is **validated against a Pydantic model**
(`ReviewResponse`) before it leaves the API, and every field is coerced and clamped, so a malformed
model reply degrades to defaults rather than a 500. And the review is given the *real* execution
results, so it is reasoning over evidence rather than a guess.

**F2. What happens with no API key?**
`ai_reviewer.py` falls back to a deterministic rule-based reviewer, and the response is tagged
`source: "heuristic"` so the UI can show an "Offline review" badge. The whole workflow still runs
end to end. That is deliberate: a demo that dies because a free-tier key expired is a bad demo.

**F3. Gemini first, Groq second — why not load-balance or route on cost?**
Because the demo's before/after score comparison only means something if both reviews come from the
same model. Silently switching providers between calls would make scores drift for reasons that
have nothing to do with the student's code. Groq is reached only after Gemini exhausts its own
retries.

**F4. What happens when Gemini returns 429 or 503?**
429, 500, 502, 503 and 504 are retried with exponential backoff (base 1s, capped at 10s, 3 attempts).
A 400 is never retried. The subtle part is the rate limit: Gemini does **not** send a `Retry-After`
header — it puts the wait in the body under `google.rpc.RetryInfo` — so both are checked, because
guessing at a backoff cannot beat being told. And if the provider asks for a wait longer than 8s,
the call **fails fast** instead of holding the student's request open against a quota that has not
reset. `check_retry_policy.py` replays real captured error bodies to prove all of that.

**F5. Why is the model never pinned to a specific version?**
`gemini-flash-latest`, not `gemini-2.5-flash`. Pinned names get retired for new API keys and start
returning 404 — which would silently break the review feature. The alias follows whatever flash
model is current.

**F6. Is the review deterministic?**
Not in LLM mode — temperature is 0.25, so it is stable but not fixed. That is why the heuristic
reviewer exists: it is the deterministic path, and it is what the tests can assert against.

**F7. Where is the review's biggest weakness?**
It asks the model *what the complexity is*, which is a claim the system cannot check. That is
exactly what Phase 5 exists to fix: measure the growth instead of asking. And I would rather ship
the measurement late than ship a confident wrong answer early — a review that tells a student their
optimal solution is quadratic is worse than no complexity claim at all.

---

## G. Database and persistence

**G1. Why Postgres and not SQLite?**
Sign-in became mandatory, so users, runs, reviews and drafts all need to persist, and the app is
already running a native Postgres service on the machine. SQLite was the MVP answer; it is
historical.

**G2. Why is `tests` JSONB rather than a child table?**
Because it is always read back as a whole and never queried field-by-field. Normalising it would
add two tables and a join for no benefit. `error` is the same.

**G3. What is the saved-drafts uniqueness rule?**
One row per `(user_id, problem_id, language)` — enforced by a `UniqueConstraint`, not by
application logic. `language` is in the key because a Python draft and a JavaScript draft for the
same problem are different pieces of work, not two versions of one. Without it, switching the
language selector would load the other language's code into the editor.

**G4. A run succeeds but the history write fails. What happens?**
The student keeps their result. Persistence is wrapped so a failed write is logged loudly and
`submission_id` comes back `null` — the run is the deliverable, the record is only a record *of* it.
The same rule applies to reviews: a failed review write must not take the feedback away.

**G5. How do migrations work?**
Alembic. Two things that bite: `alembic.ini`'s `sqlalchemy.url` stays **empty** — `env.py` reads
`DATABASE_URL` from `app.config` — and `models/__init__.py` must re-export every model, or
autogenerate silently omits that table.

**G6. What is the N+1 query you avoided?**
`GET /api/submissions` reads `row.review` per row. It uses `selectinload` rather than a lazy load,
so it is one extra query instead of one per submission.

---

## H. Auth and security

**H1. Where are passwords stored?**
Nowhere. Clerk owns sign-up, sign-in and password storage. This codebase verifies session tokens and
nothing else — there is no password hashing and no token signing anywhere in it.

**H2. How does a Clerk user become a local user row?**
Provisioned on first sight in `deps.current_user()`, not by a Clerk `user.created` webhook — a
webhook needs a publicly reachable URL and a localhost dev server does not have one. The tradeoff,
accepted knowingly: a user deleted in Clerk leaves their local row behind. Nothing reads Clerk's
user list, so that row is simply never reached again.

**H3. Two concurrent first requests both miss the SELECT. What happens?**
The unique constraint on `clerk_user_id` is what actually prevents a duplicate. The losing request
catches `IntegrityError`, rolls back, and re-reads the winner's row instead of failing. Losing that
race is expected, not a bug.

**H4. Why 503 when Clerk is not configured, instead of 401?**
Because a 401 sends the student hunting for a problem with their token when the real cause is a
missing server key — which no amount of signing in again will fix. 401 means "your credential is
bad"; 503 means "this server cannot check credentials at all".

**H5. Can student code steal the API keys?**
Not through the sandbox: `--network none` and a stripped environment. On the host backend there is
no container, which is precisely why that backend is opt-in and the child environment is an
explicit allow-list (`PATH`, `SYSTEMROOT`, `TEMP`, …) rather than inherited `os.environ`.

**H6. Any other injection surface?**
The runner never uses a shell — every `subprocess.run` takes a fixed argv list, no `shell=True`. The
docker command is built from constants and config, never from student input. The student's code
travels as a JSON field, not as a filename or an argument.

**H7. What about rate limiting?**
**Not implemented, and this is a real gap.** The Gemini free tier allows 5 requests per minute and
nothing throttles `/api/reviews`, so three people clicking during a demo can hit 429. The plan
(Phase 7) is a simple in-process token bucket keyed on the Clerk `sub`, no Redis. The Groq fallback
absorbs most of it in practice, which is why it has not bitten yet.

---

## I. Frontend

**I1. Why React + Vite, and why plain CSS?**
Vite for the dev-server speed; React because the workspace is genuinely stateful (editor, run
results, review, language selection, draft autosave). Plain CSS with custom properties rather than
Tailwind or shadcn — a design system was already produced and locked in `design.md`, and adding a
utility framework on top would have meant maintaining two systems. `build` is plain `vite build`,
which is worth knowing: **it does not type-check**, so `tsc --noEmit` has to be run explicitly.

**I2. How does the frontend stay in sync with the backend contract?**
`frontend/src/types/index.ts` mirrors `backend/app/schemas/submission.py` by hand, and
`api.ts` is the only module that speaks HTTP. The weak point is that the mirroring is manual — which
is why `check_runner.py` section 14 drives the **real ASGI app** through `POST /api/submissions/run`
and validates the payload against the real response model. A field renamed on one side of that
boundary is a 500 the student sees while the runner stays perfectly correct, and neither `tsc` nor
the other checks would catch it.

**I3. What is the `stale` state in the workspace?**
A run is marked stale when the code **or the language** changes after it. Marking it only on code
change would let a student switch Python → JavaScript and still be looking at the previous
language's results.

**I4. Where is the language choice remembered?**
Per problem id, in `localStorage`, by `WorkspaceRoute`.

**I5. What is the beams background, and why is it guarded?**
A canvas animation on the marketing pages. It is perf-guarded — 30fps cap, `MAX_DPR` 1.5, paused when
the tab is hidden, and disabled under reduced-motion — and those guards are not to be removed. On
app pages it still renders but is inert, in its own fixed layer, so no *new* enrichment is added
where function should carry the page.

**I6. Why a native `<select>` for the language picker?**
The page already sets `color-scheme: dark`, so the OS draws a matching option list, and keyboard,
focus and screen-reader support come for free instead of being reimplemented in a custom popover.

---

## J. Testing and verification

**J1. What is your test strategy?**
Three scripts, no test framework, all in `backend/scripts/`. This is a deliberate choice for the
scope, and a known limitation:
- `check_runner.py` — offline. No server, no token, no API quota. 15 numbered sections.
- `check_retry_policy.py` — replays real captured Gemini and Groq error bodies through the retry
  logic. Proves a 503 backs off and retries, a 429 asking for a long wait fails fast, a 400 is never
  retried, and a Gemini failure reaches Groq while a Gemini *success* never touches it.
- `smoke_test.py` — needs both servers running **and** a Clerk token, because sign-in is mandatory.
  It walks every endpoint the UI calls.

**J2. Why does the smoke test need `--token`?**
Because Phase 2 made sign-in mandatory, so `POST /api/submissions/run` and `POST /api/reviews` answer
401 to an anonymous caller. Without a token those sections skip with a warning rather than reporting
false failures.

**J3. Which section of the runner check would you show me first?**
Section 10 — it proves the sandbox actually isolates. Student code cannot reach the network, a
runaway allocation is stopped and told *why*, an infinite loop is killed at the per-case timeout
without losing the other cases, and no container outlives its request. Those four probes are
permanent assertions, not a one-off manual test.

**J4. What is the most useful bug your tests caught?**
Two, and both were the same class of mistake:
1. **A threshold measured on a loaded machine.** The JavaScript performance case *passed* when it
   should have failed — the naive solution finished in 2.64s against a 3s limit, a 10% margin. The
   `n = 100,000` figure had been measured during a suite run that took 3m07s instead of 1m37s, i.e.
   on a busy machine. Re-measured idle, `n` is now **200,000**, where the naive solution needs 10.48s
   against the optimal one's 0.06s.
2. **The stale sandbox image.** The image was built at 13:41; the harness was edited at 13:49. The
   result was not an error — truncated output simply arrived *without* the `stdout_truncated` flag,
   so the UI would have shown a cut-off transcript with no explanation. That is the same failure
   mode as a stale uvicorn: everything succeeds and behaves like the old version.

**J5. How do you stop a stale image from happening again?**
`check_runner.py` section 11 compares each image's build time against the newest of its source files
and fails with the exact rebuild command. Section 12's output bound is read from the harness
*source*, so a stale image fails there too.

**J6. Why are there no `pytest` tests?**
Honest answer: because the two hand-rolled scripts came first and were good enough to catch real
bugs, and Phase 7 lists `pytest` as a genuine gap. Four language harnesses, a driver generator, a
comparator and a complexity classifier cannot be maintained by a smoke script forever. What I would
say in defence is that the *comparator and driver generator* tests need no Docker and no network, so
they are the obvious first pytest targets.

**J7. How do you verify the demo number itself, not just "it works"?**
The suite asserts that problem 1 scores **exactly `3/4`** with the nested-loop solution, on the
subprocess runner, before Docker is involved. If the refactor had changed the headline number, the
demo would stop telling its story — so the number is an assertion, not an observation.

---

## K. Performance and complexity measurement

**K1. What is the difference between `elapsed` and `compute`?**
`elapsed` is wall clock for the case, *including* process startup and container overhead. `compute`
is seconds spent **inside the student's own code**. On Windows, spawning a process costs 0.59–1.0s
and a container costs another ~2s, against roughly 20µs of actual work for a trivial case — so
`elapsed` is 99.998% *our* overhead, not theirs. Only `compute` is usable for complexity analysis.

**K2. How do you know `compute` is measuring the student's code and not the interpreter boot?**
A function that ignores its input entirely stays flat at **1.26× across 16× the input**. If it were
measuring interpreter startup it would not stay flat.

**K3. Why not classify complexity from a single doubling?**
Because the signal does not clear the noise. Measured pairwise ratios for a genuinely *linear*
solution came out **2.63, 1.64, 2.74, 1.31** — right on average, but noisy enough that one pair
reads as ~1.0, because its absolute time is under a millisecond. Quadratic at the same sizes read
4.11 and 3.92. So the comparison is done **per doubling across a range**, best-of-several-runs.

**K4. Why does the JavaScript ladder start at 8,000 and not 1,000?**
Because V8 JITs a tight loop and CPython does not. In JavaScript the naive solution reads
**1.31× / 1.86× per doubling** from 1,000 → 8,000, which looks *sublinear*, because V8 is still
interpreting the inner loop and the JIT speedup nearly cancels the quadratic growth. From 8,000 →
64,000 the same code reads 3.04 / 3.69 / 3.47 / 3.97×. The ladder floor is therefore **per-language**.

**K5. What is still open in Phase 5?**
The classification rule. And this is the most interesting unfinished problem in the project, so it is
worth being able to explain properly:

Problem 1's own **optimal** solution — a hash set, genuinely O(n) — measures **2.54× / 2.68× / 3.15×
per doubling against an ideal 2.0×**, because hash-table growth is allocation-bound and rehashes in
steps. A fixed threshold would therefore call an optimal solution quadratic. The fix is to measure a
**known-linear baseline on the same ladder, in the same container, in the same run**, and classify
the student's growth *relative to that* — which also cancels machine load and JIT state.

**K6. Why not just ship a fixed threshold and move on?**
Because getting this wrong is worse than not shipping it. A confidently wrong complexity claim is
exactly what the project's own rule against the model inventing things exists to prevent.

**K7. Two absolute wall-clock bounds were written and withdrawn. Why?**
Because neither was stable. The same submission measured 2.25–2.62s once and 3.87–8.17s later with
nothing changed. A tight bound that fires spuriously only teaches you to ignore failures. What
survives is the **structural** property — one `docker run` per submission — which is
load-independent and is asserted directly.

**K8. What is the honest cost of a submission?**
**~4–5s wall clock, occasionally more.** Do not quote the old 2.45s median; it was measured once and
never reproduced. A cold first run is slower while the image layers page in, which is worth knowing
before a demo — run one throwaway submission after starting the daemon.

**K9. Why is a measurement that did not happen recorded as `None` and never `0.0`?**
Because a zero reads as an infinitely fast solution, which would classify as **constant time** — the
exact opposite of the truth for a submission that timed out.

**K10. Was there a time when the measurements were just wrong?**
Yes, and it is worth telling because it shows the diagnosis rather than the excuse. The *same* code
at the *same* size came in **34× slower** than the recorded ladder — 1.33s against 39ms at n=8,000.
An A/B of the two input mechanisms agreed to within 7%, so the input was not the cause. **C: was at
100% full: 86 MB free of 232 GB.** Docker Desktop and Windows both thrash when the system drive is
full. That is the third time this project paid for picking a number off a loaded machine, and the
first time the cause was identified rather than only observed. The consequence: `DEFAULT_SIZES` and
`SCALING_TIMEOUT_SECONDS` are configurable and deliberately **untuned** — a shape, not a measurement.

---

## L. Trade-offs and limitations — the honest section

Have these ready. A teacher who asks "what is wrong with this" and hears "nothing" has learned that
you cannot evaluate your own work.

| Limitation | The honest framing |
|---|---|
| Java and C++ not implemented | Phase 6, deliberately last so everything before it is demonstrable. The four-language claim is a *plan*, not a build — do not overclaim it. |
| Complexity classification open | The measurement ladder works; the *relative baseline* rule does not exist yet. A fixed threshold would misclassify an optimal hash-set solution. |
| No `pytest` | Three purpose-built scripts instead. Works, but does not scale to four harnesses and a driver generator. |
| No rate limiting on `/api/reviews` | Gemini free tier is 5/min; three demo clicks can 429. Groq absorbs most of it. |
| Instructor view out of scope | Considered and rejected, not forgotten. |
| No hosting, no CI | A locked scope decision — the target is a local demo. |
| `problem_id` is not a foreign key | The catalogue is JSON, so a stored run can outlive its problem. Handled with a fallback label rather than a join. |
| The host backend has no isolation | It is the explicit fallback for when Docker is down. Never automatic, and Python-only. |
| Wall-clock is slow | ~4–5s per submission on Windows. Accepted and measured; the sandbox is the trade. |
| Manual type mirroring | `types/index.ts` mirrors the Pydantic schemas by hand. Section 14 of the runner check is the guard against drift. |

**If asked "what is the single weakest part of this project?"** — the complexity classifier is the
weakest *feature*; the lack of `pytest` is the weakest *engineering*; and the four-language content
backfill (48 starters and signatures) is the weakest *estimate*.

---

## M. Curveballs

**M1. "Your AI review is just an LLM wrapper. What did you actually engineer?"**
The review is the least engineered part on purpose — it is one seam in one function. The
engineering is: a hardened execution sandbox with per-case process isolation and cgroup-level OOM
attribution; a language-agnostic test contract that replaced a Python-only format *before* a second
language existed; comparison centralised so tolerance rules exist once instead of four times; a
measurement instrument that separates interpreter startup from algorithmic work; and a retry policy
calibrated against real captured provider failures.

**M2. "Why should I believe your numbers?"**
Because where a number was not stable I withdrew it and said so. Two wall-clock bounds and one
JavaScript threshold were written and retracted the same day, each time because a re-measurement
disagreed. What is asserted is structure — one container per submission, no leftover containers, the
demo scores exactly 3/4 — because structure is load-independent and timing is not.

**M3. "What happens if two students run code at the same time?"**
Each gets its own container, so they cannot see each other. The API is sync-handler-based, so
FastAPI runs them in worker threads. It is not designed for scale — `DB_POOL_SIZE` is 5, and the
scope is explicitly single-machine. What it *is* designed for is that one student's infinite loop
cannot affect another's run, which the container guarantees.

**M4. "Show me a piece of code you are proud of."**
`_CappedBuffer`. The first version reported a runaway `print` loop as an out-of-memory failure —
technically true, completely useless, because the student's actual mistake was printing too much.
Capping on write keeps memory flat and lets the result carry an honest truncation flag. There is a
second subtlety in it: the first version tested `size >= limit` after every write, so output landing
on exactly 4,000 characters was labelled truncated although nothing had been lost. It now sets the
flag only when a write is actually cut short — and the JavaScript harness keeps byte-identical
semantics, asserted by the test suite.

**M5. "Why is `oom_killed` false rather than null on the sandbox?"**
Because on the sandbox we *looked* and it did not happen. On the host there is no cgroup, so the
answer is "I cannot tell you", which is `None`. The distinction is deliberate and asserted in both
directions, so the UI can never confuse the two.

**M6. "If Docker Desktop fails during your demo, what do you do?"**
Set `RUNNER_BACKEND=subprocess` and restart the backend. Python still runs, without isolation, and
`/api/health` says so. That is exactly why the fallback exists — the alternative is a demo that
cannot run because a daemon did not start.

**M7. "Why does `--read-only` not use `noexec` on `/work`?"**
Because Java and C++ compile a binary there and must run it. `nosuid` stays. That constraint is worth
raising proactively — it shows the flags were chosen, not copied.

**M8. "Isn't one container per submission wasteful?"**
It is the *opposite* of wasteful. The container is what isolates the student from the host, and that
cost is paid once. The child processes inside give per-case timeouts and crash isolation at
near-zero cost. A container per case would pay the ~2s lifecycle four times for no additional
safety.

**M9. "What did you get wrong that you only found by running the thing?"**
Three, and all three are in the plan's trap notes: the stale sandbox image (silent, and the worst
kind — every run succeeds and behaves like the old code); a wall-clock bound calibrated on Docker
and then applied to the host backend (which failed it, correctly, because Windows process spawn
costs 3–4× what an in-container spawn does); and an OOM probe that must not *run* on the host
backend, not merely skip its assertion, because on the host there is no cgroup to stop it.

**M10. "Why `3/4` and not `failed`?"**
`_determine_status` reserves `failed` for a run where **nothing** passed. 3 of 4 is `partial`, and
the UI colours it amber. This was originally asserted wrong from memory, and the test suite caught
it — which is the argument for asserting the status rather than just the count.

---

## N. Numbers cheat sheet

Memorise these; quoting a wrong number is worse than saying "I'd have to check".

| Thing | Value |
|---|---|
| Problems / test cases | **12 / 49** |
| Languages built | **2** — Python, JavaScript |
| Languages planned | 4 — Java and C++ are Phase 6 |
| Sandbox images | `codereviewer-runner-python` (`python:3.12-slim`), `codereviewer-runner-node` (`node:22-slim`) |
| Container limits | 512 MB · 1 CPU · 128 pids · 128 MB tmpfs · nobody · no caps · no network |
| Containers per submission | **exactly 1** |
| Demo number | problem 1, nested loop → **3/4**, status `partial` |
| Performance case | 200,000 elements, 3s limit; naive **10.48s** in JS, optimal **0.06s** |
| JS ladder floor | **n = 8,000** (V8 JIT) |
| stdout cap | **4,000** chars, `stdout_truncated` flag |
| Default sizes | `(4_000, 16_000, 64_000)` — **untuned** |
| Test / submission / scaling timeouts | 3s · 20s · 40s |
| LLM | Gemini `gemini-flash-latest` → Groq `openai/gpt-oss-120b`, temp 0.25, 3 attempts |
| Real submission cost | **~4–5s** wall clock (do not quote 2.45s) |

---

## O. A demo script that survives questions

Run it in this order, and say the *why* out loud as you go — the reasoning is what is being graded.

1. **`/api/health`** — show `runner_backend: docker`, `docker_ok: true`. *"The health endpoint exists
   because two of this project's failure modes are silent."*
2. **Problem 1, Python, nested-loop solution, Run** — `3/4`, `partial`, the failing case named, its
   per-case time, and the truncated-output marker if you print anything.
3. **Switch to JavaScript, Run again** — the *same* `3/4`. *"Same case, same mechanism, different
   runtime."*
4. **Ask for the review** — point at the specific construct it names, and the hint/approach split.
5. **Break it on purpose** — an infinite loop (killed at the per-case timeout, other cases
   survive), then a huge allocation (OOM, with the ceiling named). *"A student should never see a
   stack trace."*
6. **Show the history and the dashboard** — the run you just did is in it.

Have ready, but do not lead with: the `RUNNER_BACKEND=subprocess` fallback, and
`check_runner.py` section 10.

**Before you demo:** run `check_runner.py` and quote the live number, not a remembered one. Start
the daemon, run one throwaway submission so the image layers are warm, and check free space on `C:`.
