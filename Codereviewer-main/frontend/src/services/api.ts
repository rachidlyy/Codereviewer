/**
 * Thin client for the CodeReviewer backend.
 *
 * This module is the only place in the frontend that knows about HTTP. Every
 * screen goes through these four calls, which map one-to-one onto the API
 * contract in the plan:
 *
 *   fetchProblems()  -> GET  /api/problems
 *   fetchProblem()   -> GET  /api/problems/{id}
 *   runCode()        -> POST /api/submissions/run
 *   requestReview()  -> POST /api/reviews
 */

import type {
  Health,
  Problem,
  ProblemSummary,
  Review,
  RunResult,
  TestResultSummary,
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
  let response: Response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
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

export function requestReview(
  problemId: number,
  code: string,
  testResult: TestResultSummary,
): Promise<Review> {
  return request<Review>('/api/reviews', {
    method: 'POST',
    body: JSON.stringify({
      problem_id: problemId,
      code,
      test_result: testResult,
    }),
  });
}

export function fetchHealth(): Promise<Health> {
  return request<Health>('/api/health');
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
