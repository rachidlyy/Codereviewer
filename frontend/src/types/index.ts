/**
 * Shared types.
 *
 * These mirror the FastAPI schemas in `backend/app/schemas/submission.py`.
 * If a field changes on the server it must change here too.
 */

export type Difficulty = 'Easy' | 'Medium';

/** Languages the backend can actually execute (see code_runner.py's LANGUAGE_RUNNERS). */
export type SupportedLanguage = 'python' | 'javascript';

/** Display label, Monaco editor language id, and starter filename per language. */
export const LANGUAGE_META: Record<
  SupportedLanguage,
  { label: string; monacoLanguage: string; fileName: string }
> = {
  python: { label: 'Python 3', monacoLanguage: 'python', fileName: 'main.py' },
  javascript: { label: 'JavaScript', monacoLanguage: 'javascript', fileName: 'main.js' },
};

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
 * Shape returned by `GET /api/problems/{id}`. `starter` is now keyed by
 * language (e.g. `{ python: "...", javascript: "..." }`) instead of being a
 * single string, so the editor can load the right boilerplate for whichever
 * language is selected.
 */
export type Problem = ProblemSummary & {
  starter: Partial<Record<SupportedLanguage, string>>;
  entrypoint: string;
};

export type RunStatus = 'passed' | 'partial' | 'failed' | 'error' | 'timeout';

/**
 * `actual` and `expected` are now arbitrary JSON values (numbers, strings,
 * booleans, arrays) rather than pre-stringified text - the backend used to
 * send Python `repr()` strings, but now every language reports real JSON so
 * comparisons work the same way no matter which language produced them.
 */
export type TestCaseResult = {
  index: number;
  name: string;
  passed: boolean;
  error_type: string | null;
  message: string | null;
  actual: unknown;
  expected: unknown;
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
