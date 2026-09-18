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
};
