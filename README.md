# CodeMentor AI

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
| AI | Google Gemini (REST), behind a swappable service module |
| Data | In-memory Python structures — **no database** |
| Execution | Local Python subprocesses with per-test timeouts |

---

## Layout

```
.
├── frontend/
│   ├── src/
│   │   ├── components/     # Header, ProblemCard, ProblemPanel, EditorPanel,
│   │   │                   # TestResults, ReviewPanel
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

---

## Two-minute demo

1. **0:00** — Open the problem list.
2. **0:20** — Select **Contains Duplicate**.
3. **0:35** — Paste the intentionally inefficient O(n²) solution:

   ```python
   def containsDuplicate(nums):
       for i in range(len(nums)):
           for j in range(i + 1, len(nums)):
               if nums[i] == nums[j]:
                   return True
       return False
   ```

4. **0:50** — Click **Run Code** → `3/4 tests passed` (partial).
5. **1:10** — Click **Get AI Review** → scores, the quadratic-runtime issue,
   and `Current: O(n²)` vs `Suggested: O(n)`.
6. **1:40** — Click **Show Hint**, then **View Improved Approach**.

The point to make out loud: *the system does not rely on the LLM alone. The
code is tested first, and the AI receives the problem, the submitted code
and the real execution results.*

---

## Notes for the team

**Code execution is not sandboxed.** Student code runs as a local
subprocess with a timeout, a stripped environment (the API key is never
visible to it) and an isolated working directory. That is deliberate for a
one-week MVP. Everything execution-related lives in
`backend/app/services/code_runner.py`, so swapping in a Docker sandbox later
means reimplementing one function.

**The LLM is behind one module.** `backend/app/services/ai_reviewer.py` is
the only file that talks to a provider. To switch to OpenAI, rewrite
`_call_llm`; nothing else changes.

**No database.** `backend/app/data/problems.py` and `test_cases.py` hold the
data. The accessor functions at the bottom of `problems.py` are the seam to
replace when moving to PostgreSQL.

**Changing the API shape?** Update `backend/app/schemas/submission.py` and
`frontend/src/types/index.ts` together — they must stay in sync.
