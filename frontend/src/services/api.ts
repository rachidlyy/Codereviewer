/**
 * Thin client for the CodeReviewer backend.
 *
 * This module is the only place in the frontend that knows about HTTP. Every
 * screen goes through these calls, which map one-to-one onto the API
 * contract in the plan:
 *
 *   fetchProblems()    -> GET  /api/problems
 *   fetchProblem()     -> GET  /api/problems/{id}
 *   runCode()          -> POST /api/submissions/run
 *   requestReview()    -> POST /api/reviews
 *   fetchSubmissions() -> GET  /api/submissions
 *   fetchSubmission()  -> GET  /api/submissions/{id}
 *   fetchProgress()    -> GET  /api/progress
 *   fetchSavedCode()   -> GET  /api/saved-code/{id}
 *   saveCode()         -> PUT  /api/saved-code/{id}
 *   fetchHealth()      -> GET  /api/health
 *   fetchMe()          -> GET  /api/auth/me
 *
 * Every request carries the Clerk session token as a Bearer header when one
 * is available, so the callers below do not each have to remember to add it.
 */

import { getSessionToken } from './clerkToken';
import type {
  Health,
  Problem,
  ProblemSummary,
  Progress,
  Review,
  RunResult,
  SavedCode,
  SubmissionDetail,
  SubmissionSummary,
  TestResultSummary,
  User,
} from '../types';

/** Backend base URL. Override with VITE_API_URL in a `.env` file. */
const API_BASE = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');

/** Error carrying a message that is safe to show the student directly. */
export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const OFFLINE_MESSAGE =
  'Could not reach the CodeReviewer API. Make sure the backend is running on ' + API_BASE + '.';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Attach the Clerk session token when there is one. The getter is
  // registered by <AuthTokenBridge/>; see services/clerkToken.ts for why this
  // cannot call useAuth() directly.
  const token = await getSessionToken();

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // Caller-supplied headers win, so a future endpoint can override.
      headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
    });
  } catch {
    // fetch only rejects on network-level failure, i.e. the backend is down.
    throw new ApiError(OFFLINE_MESSAGE, null);
  }

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }

  return (await response.json()) as T;
}

/**
 * FastAPI reports errors as `{"detail": "..."}`. Fall back to the status
 * text if the body is not the shape we expect.
 */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return 'The request was rejected by the server.';
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (HTTP ${response.status}).`;
}

export function fetchProblems(): Promise<ProblemSummary[]> {
  return request<ProblemSummary[]>('/api/problems');
}

export function fetchProblem(problemId: number): Promise<Problem> {
  return request<Problem>(`/api/problems/${problemId}`);
}

export function runCode(
  problemId: number,
  code: string,
  language = 'python',
): Promise<RunResult> {
  return request<RunResult>('/api/submissions/run', {
    method: 'POST',
    body: JSON.stringify({ problem_id: problemId, language, code }),
  });
}

/**
 * Review a run.
 *
 * `submissionId` is the id returned by `runCode`. Passing it lets the backend
 * record the review against that run so it appears in history; omitting it
 * still returns a review, it just is not saved.
 */
export function requestReview(
  problemId: number,
  code: string,
  testResult: TestResultSummary,
  submissionId: number | null = null,
): Promise<Review> {
  return request<Review>('/api/reviews', {
    method: 'POST',
    body: JSON.stringify({
      problem_id: problemId,
      code,
      test_result: testResult,
      submission_id: submissionId,
    }),
  });
}

/** The student's own runs, newest first. Pass a problem id to filter. */
export function fetchSubmissions(problemId?: number): Promise<SubmissionSummary[]> {
  const query = problemId === undefined ? '' : `?problem_id=${problemId}`;
  return request<SubmissionSummary[]>(`/api/submissions${query}`);
}

/** One saved run, including its code, test results and review. */
export function fetchSubmission(submissionId: number): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/api/submissions/${submissionId}`);
}

/** Per-problem progress across the whole catalogue, plus overall counts. */
export function fetchProgress(): Promise<Progress> {
  return request<Progress>('/api/progress');
}

/**
 * The student's saved draft for a problem.
 *
 * `code` comes back null when nothing has been saved, which is where every
 * problem starts. A draft is a convenience rather than a prerequisite, so
 * callers should treat a failure here as "no draft" and carry on with the
 * starter code rather than blocking the workspace.
 */
export function fetchSavedCode(problemId: number): Promise<SavedCode> {
  return request<SavedCode>(`/api/saved-code/${problemId}`);
}

/** Replace the saved draft for a problem. One row per user and problem. */
export function saveCode(problemId: number, code: string): Promise<SavedCode> {
  return request<SavedCode>(`/api/saved-code/${problemId}`, {
    method: 'PUT',
    body: JSON.stringify({ code }),
  });
}

export function fetchHealth(): Promise<Health> {
  return request<Health>('/api/health');
}

/**
 * The signed-in user, resolved from the Clerk session token.
 *
 * Doubles as the "is my token still good?" probe: a 401 means the client
 * should sign the user out rather than retry.
 */
export function fetchMe(): Promise<User> {
  return request<User>('/api/auth/me');
}

/** Reduce a run result to the summary the review endpoint expects. */
export function toTestResultSummary(result: RunResult): TestResultSummary {
  return {
    passed: result.passed,
    total: result.total,
    execution_time: result.execution_time,
    status: result.status,
    failed_tests: result.tests.filter((test) => !test.passed).map((test) => test.name),
  };
}
