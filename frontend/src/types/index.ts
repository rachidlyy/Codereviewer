/**
 * Shared types.
 *
 * These mirror the FastAPI schemas in `backend/app/schemas/submission.py`.
 * If a field changes on the server it must change here too.
 */

export type Difficulty = 'Easy' | 'Medium';

export type ProblemExample = {
  input: string;
  output: string;
};

/** Shape returned by `GET /api/problems`. */
export type ProblemSummary = {
  id: number;
  title: string;
  difficulty: Difficulty;
  category: string;
  description: string;
  examples: ProblemExample[];
  tags: string[];
};

/**
 * Shape returned by `GET /api/problems/{id}`. Adds the starter code the
 * editor is seeded with and the function name the runner calls.
 */
export type Problem = ProblemSummary & {
  starter: string;
  entrypoint: string;
};

export type RunStatus = 'passed' | 'partial' | 'failed' | 'error' | 'timeout';

export type TestCaseResult = {
  index: number;
  name: string;
  passed: boolean;
  error_type: string | null;
  message: string | null;
  actual: string | null;
  expected: string | null;
};

/** Friendly, student-facing error copy produced by the backend. */
export type RunError = {
  type: string;
  title: string;
  message: string;
  line: number | null;
  detail: string | null;
};

export type RunResult = {
  status: RunStatus;
  passed: number;
  total: number;
  execution_time: number;
  tests: TestCaseResult[];
  error: RunError | null;
  /**
   * The id of the saved run this result was recorded as, so the review can be
   * attached to it. `null` means the run itself succeeded but recording it
   * failed — the result is still valid and reviewable, it just will not
   * appear in history.
   */
  submission_id: number | null;
};

export type ReviewIssue = {
  type: string;
  title: string;
  explanation: string;
};

export type ReviewComplexity = {
  current_time: string;
  current_space: string;
  suggested_time: string;
  suggested_space: string;
};

/** Shape returned by `POST /api/reviews`. */
export type Review = {
  overall_score: number;
  correctness_score: number;
  readability_score: number;
  efficiency_score: number;
  summary: string;
  issues: ReviewIssue[];
  suggestions: string[];
  complexity: ReviewComplexity;
  hint: string;
  /** Revealed only when the student asks for it. */
  improved_approach: string;
  /**
   * Which reviewer produced this. `gemini` is the primary model, `groq` the
   * fallback used when Gemini is unavailable, and `heuristic` means no LLM was
   * configured so the feedback is rule-based.
   */
  source: 'gemini' | 'groq' | 'heuristic';
};

/** The subset of a run result sent along with a review request. */
export type TestResultSummary = {
  passed: number;
  total: number;
  execution_time: number;
  status: RunStatus;
  failed_tests: string[];
};

export type Health = {
  status: string;
  llm_configured: boolean;
  llm_model: string | null;
  problems: number;
  /** Phase 2: sign-in is mandatory, so the database is load-bearing. */
  database_configured: boolean;
  database_ok: boolean;
  database_error: string | null;
  auth_configured: boolean;
};

/**
 * Mirrors `UserOut` in `backend/app/schemas/user.py`.
 *
 * Clerk owns identity, so this is the *local* row rather than the source of
 * truth. `email` and `display_name` are optional because a Clerk session
 * token carries the `sub` claim but not the profile fields unless the Clerk
 * application defines a custom JWT template that adds them — so the UI must
 * treat a missing name as normal.
 */
export type User = {
  id: number;
  clerk_user_id: string;
  email: string | null;
  display_name: string | null;
  created_at: string;
};

/** Shape returned by `GET /api/submissions`. */
export type SubmissionSummary = {
  id: number;
  problem_id: number;
  problem_title: string;
  problem_difficulty: string;
  status: RunStatus;
  passed: number;
  total: number;
  execution_time: number;
  created_at: string;
  /** From the attached review, when one exists. */
  overall_score: number | null;
  review_source: Review['source'] | null;
};

/** Shape returned by `GET /api/submissions/{id}` — enough to replay the run. */
export type SubmissionDetail = SubmissionSummary & {
  language: string;
  code: string;
  tests: TestCaseResult[];
  error: RunError | null;
  review: Review | null;
};

/** One problem's row on the dashboard, attempted or not. */
export type ProblemProgress = {
  problem_id: number;
  title: string;
  difficulty: string;
  attempted: boolean;
  /** True once any single run passed every test case. */
  solved: boolean;
  attempts: number;
  /** How many test cases the problem has, from the catalogue. */
  total_tests: number;
  best_passed: number;
  best_score: number | null;
  last_attempt_at: string | null;
};

/** Shape returned by `GET /api/progress` — the whole dashboard in one call. */
export type Progress = {
  total_problems: number;
  attempted_problems: number;
  solved_problems: number;
  total_submissions: number;
  average_score: number | null;
  /** Covers the whole catalogue, not only the attempted problems. */
  problems: ProblemProgress[];
};
