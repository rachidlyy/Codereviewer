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
 * How one problem is attempted in one language.
 *
 * `entrypoint` is the function the harness calls, `params`/`returns` are the
 * declared signature, and `starter` seeds the editor.
 */
export type LanguageSpec = {
  entrypoint: string;
  params: string[];
  returns: string;
  starter: string;
};

/**
 * Shape returned by `GET /api/problems/{id}`.
 *
 * `languages` is a map rather than a flat `starter`/`entrypoint` pair because
 * a problem can be attempted in more than one language. A language absent
 * from the map is one this problem cannot be attempted in.
 */
export type Problem = ProblemSummary & {
  languages: Record<string, LanguageSpec>;
};

export type RunStatus = 'passed' | 'partial' | 'failed' | 'error' | 'timeout';

export type TestCaseResult = {
  index: number;
  name: string;
  passed: boolean;
  error_type: string | null;
  message: string | null;
  /** `repr` of what the student's code returned, and of what was expected. */
  actual: string | null;
  expected: string | null;
  /**
   * The same two values as real JSON, for structural diffing.
   *
   * `null` when the value was too large or could not be represented, in which
   * case fall back to the reprs above — those are always present.
   */
  actual_value?: unknown;
  expected_value?: unknown;
  /** Wall-clock seconds this case took, including process startup. */
  elapsed: number;
  /**
   * Seconds spent inside the student's own code, excluding interpreter
   * startup. This is the number worth showing a student — `elapsed` is
   * dominated by process spawn on Windows.
   */
  compute: number;
  /** Anything the student printed while this case ran. */
  stdout: string | null;
  /**
   * True when that output was cut short. The harness stops buffering at 4000
   * characters instead of accumulating a runaway print loop in memory, so this
   * means "you printed a lot" — not "something broke".
   */
  stdout_truncated?: boolean;
  /** Clean exit status. Null when the child was killed by a signal. */
  exit_code?: number | null;
  /** Number of the signal that killed the child. Null on a clean exit. */
  signal?: number | null;
  /**
   * True when the kernel's OOM killer ended this case. `null` means the
   * backend cannot report it (the host runner has no cgroup), which is
   * deliberately different from `false` — "we looked and it did not happen".
   */
  oom_killed?: boolean | null;
};

/**
 * What the sandbox did, as opposed to what the code did.
 *
 * Only the container backend can fill this in, so it is `null` when the host
 * runner is configured. It exists so an out-of-memory failure can be explained
 * with numbers rather than a bare SIGKILL.
 */
export type SandboxInfo = {
  memory_limit_bytes: number | null;
  /** High-water mark across the whole submission — cgroup v2's `memory.peak`
   *  is monotonic, so it cannot be attributed to one test case. */
  memory_peak_bytes: number | null;
  oom_killed: boolean;
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
  /**
   * What the sandbox did. `null` when the host runner is configured — there is
   * no container, so there is no memory ceiling to report.
   */
  sandbox: SandboxInfo | null;
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

/**
 * Shape returned by the saved-draft endpoints.
 *
 * `code` is null when this problem has never been saved *in this language*,
 * which is the normal starting state rather than an error — so callers must not
 * treat it as one.
 *
 * `language` is part of the draft's identity: a Python draft and a JavaScript
 * draft for one problem are separate rows, because the language selector makes
 * having both a normal thing to do.
 */
export type SavedCode = {
  problem_id: number;
  language: string | null;
  code: string | null;
  updated_at: string | null;
};

/**
 * Auto-save status shown beside the editor.
 *
 * `idle` means there is nothing worth reporting: either nothing has been typed
 * since the draft was loaded, or the last write is already accounted for.
 */
export type SaveState = 'idle' | 'saving' | 'saved' | 'error';
