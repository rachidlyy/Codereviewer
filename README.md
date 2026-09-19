# CodeReviewer

A web-based AI-powered coding practice and code review platform.

Pick a problem → write Python → run it against real test cases → get an
educational review from an AI mentor.

This is the **one-week MVP** described in `plan.md`: a single, complete,
demonstrable workflow rather than a broad half-finished platform.

```
PROBLEM → CODE → RUN → TEST RESULTS → AI REVIEW → IMPROVEMENT
```

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript + Vite, Monaco Editor, plain CSS |
| Backend | Python + FastAPI + Uvicorn |
| AI | Google Gemini (REST) with a Groq fallback, behind a swappable service module |
| Data | In-memory Python structures — **no database** |
| Execution | Local Python subprocesses with per-test timeouts |

---

## Layout

```
.
├── frontend/
│   ├── src/
│   │   ├── components/     # Header, ProblemCard, ProblemPanel, EditorPanel,
│   │   │                   # TestResults, ReviewPanel, BeamsBackground
│   │   ├── pages/          # ProblemsPage, WorkspacePage
│   │   ├── services/       # api.ts — the only module that speaks HTTP
│   │   ├── types/          # mirrors the backend Pydantic schemas
│   │   ├── App.tsx         # state + orchestration
│   │   └── styles.css
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI app, CORS, health
│   │   ├── config.py       # env-driven settings
│   │   ├── routes/         # problems.py, submissions.py, reviews.py
│   │   ├── services/       # code_runner.py, ai_reviewer.py
│   │   ├── data/           # problems.py, test_cases.py
│   │   └── schemas/        # submission.py (request/response models)
│   ├── scripts/            # smoke_test.py, check_retry_policy.py
│   ├── requirements.txt
│   └── .env.example
│
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

# start the API
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### 3. Enable the AI review (optional)

The app **works without this**. With no key configured, `ai_reviewer.py`
uses a built-in rule-based reviewer so the whole workflow still runs — it
just can't reason as freely as a model.

To use Gemini:

```bash
cd backend
cp .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

Get a free key at https://aistudio.google.com/apikey. Restart the backend
afterwards. `/api/health` will report `"llm_configured": true`, and the
"Offline review" badge disappears from the header.

---

## Checking it

Two scripts live in `backend/scripts/`. Neither needs anything beyond
`requirements.txt` — no test framework, no extra packages.

### Before a demo — with both servers running

```bash
cd backend
.venv/Scripts/python.exe scripts/smoke_test.py
```

Walks every endpoint the UI calls, in order, and prints a pass/fail line for
each: service identity, the problem catalogue, the starter-code contract, code
execution (including the `3/4` partial demo case), and the AI review. Exits
non-zero if anything failed.

```
  13 passed   0 failed   2 warnings
```

(A healthy run with a working key reports more passes — the review section
adds several. A `WARN` there is not a failure.)

`--no-review` skips the review section — the only part that spends API quota.
`--base-url` points it at a different port.

The starter-code check is worth keeping an eye on: it asserts that the starter
code produces `failed` rather than `error`. An `error` there means a problem's
`entrypoint` name has drifted away from its `starter` signature, which would
otherwise show up as *every* submission erroring.

### Any time — offline, no server, no key, no quota

```bash
cd backend
.venv/Scripts/python.exe scripts/check_retry_policy.py
```

Replays real captured Gemini and Groq error bodies through the retry logic and
asserts that a transient `503` backs off and retries, a `429` stating a long wait
fails fast instead of hanging the request, a `400` is never retried, and a
Gemini failure reaches Groq while a Gemini *success* never touches it.

```
  37 passed   0 failed
```

> A `WARN` in the smoke test's review section is usually the provider rather
> than a bug: the Gemini free tier allows 5 requests per minute, and the flash
> models intermittently return `503 high demand` or time out. If Groq is
> configured the fallback absorbs most of this, and the run reports
> `source=groq` for the affected reviews. See `backend/.env.example`.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/problems` | List all problems |
| `GET` | `/api/problems/{id}` | One problem, including starter code |
| `POST` | `/api/submissions/run` | Execute code against the test cases |
| `POST` | `/api/reviews` | Produce a structured AI review |
| `GET` | `/api/health` | Readiness + whether the LLM is configured |

```bash
# run a submission
curl -X POST http://127.0.0.1:8000/api/submissions/run \
  -H "Content-Type: application/json" \
  -d '{"problem_id": 1, "language": "python", "code": "def containsDuplicate(nums):\n    return len(nums) != len(set(nums))"}'
```

Run statuses: `passed` · `partial` · `failed` · `error` · `timeout`

---

## Problems

| # | Title | Difficulty |
|---|---|---|
| 1 | Contains Duplicate | Easy |
| 2 | Two Sum | Easy |
| 3 | Valid Anagram | Easy |
| 4 | Binary Search | Easy |
| 5 | Maximum Subarray | Medium |

Each problem has 3–4 test cases. Problem 1 additionally has a **large-input
performance case** (20,000 elements, 3s limit). A nested-loop solution
passes the three correctness cases but exceeds the limit on that one, which
is what produces the demo's `3/4 tests passed` — and gives the AI reviewer
something concrete to explain.

