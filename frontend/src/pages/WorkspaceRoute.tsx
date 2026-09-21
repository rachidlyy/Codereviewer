import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import WorkspacePage from './WorkspacePage';
import { fetchProblem, requestReview, runCode, toTestResultSummary } from '../services/api';
import { messageOf } from '../services/errors';
import type { ProblemSummary, Review, RunResult } from '../types';

/** A synthetic run result used when the request itself failed. */
function runFailure(message: string): RunResult {
  return {
    status: 'error',
    passed: 0,
    total: 0,
    execution_time: 0,
    tests: [],
    error: {
      type: 'network',
      title: 'Could not run your code',
      message,
      line: null,
      detail: null,
    },
    // Nothing was executed, so nothing was recorded either.
    submission_id: null,
  };
}

/**
 * Route wrapper for the coding workspace.
 *
 * Owns all the per-problem state that used to live in `App.tsx`, so navigating
 * away and back naturally resets it and a page refresh restores the problem
 * from the URL.
 */
export default function WorkspaceRoute() {
  const { problemId } = useParams<{ problemId: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const id = Number(problemId);
  const validId = Number.isInteger(id) && id > 0;

  // The catalogue passes the row it already had, so the heading is correct on
  // the first paint. A cold load (refresh, or a shared link) has no state and
  // falls back to the fetched detail below.
  const summaryFromNav = (location.state as { summary?: ProblemSummary } | null)?.summary ?? null;

  const [problem, setProblem] = useState<ProblemSummary | null>(summaryFromNav);
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(true);
  const [codeError, setCodeError] = useState<string | null>(null);

  const [lastRun, setLastRun] = useState<{ code: string; result: RunResult } | null>(null);
  const [running, setRunning] = useState(false);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  // An unusable id in the URL (e.g. /problems/abc) is a dead end; send the
  // student back to the catalogue rather than showing an empty shell.
  useEffect(() => {
    if (!validId) navigate('/problems', { replace: true });
  }, [validId, navigate]);

  useEffect(() => {
    if (!validId) return;
    // Guards against a slow response for a problem the student has already
    // navigated away from overwriting the current one.
    let cancelled = false;

    setCodeLoading(true);
    setCodeError(null);
    setCode('');
    setLastRun(null);
    setReview(null);
    setReviewError(null);

    fetchProblem(id)
      .then((detail) => {
        if (cancelled) return;
        // Also fills in the heading on a cold load, where nav state is absent.
        setProblem(detail);
        setCode(detail.starter);
      })
      .catch((err) => {
        if (!cancelled) setCodeError(messageOf(err));
      })
      .finally(() => {
        if (!cancelled) setCodeLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id, validId]);

  const handleCodeChange = useCallback((value: string) => {
    setCode(value);
    // A review describes one specific revision, so it is dropped as soon as
    // the code changes rather than silently showing mismatched feedback.
    setReview((current) => (current ? null : current));
  }, []);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setReview(null);
    setReviewError(null);
    try {
      const result = await runCode(id, code);
      setLastRun({ code, result });
    } catch (error) {
      setLastRun({ code, result: runFailure(messageOf(error)) });
    } finally {
      setRunning(false);
    }
  }, [id, code]);

  const handleReview = useCallback(async () => {
    if (!lastRun) return;
    setReviewing(true);
    setReviewError(null);
    try {
      // Review the code that was actually executed, so the feedback and the
      // test results can never disagree. The run's id travels with it so the
      // backend can attach the review to that run, which is what puts it in
      // the student's history.
      const result = await requestReview(
        id,
        lastRun.code,
        toTestResultSummary(lastRun.result),
        lastRun.result.submission_id,
      );
      setReview(result);
    } catch (error) {
      setReviewError(messageOf(error));
    } finally {
      setReviewing(false);
    }
  }, [id, lastRun]);

  const stale = lastRun !== null && lastRun.code !== code;
  const canReview = lastRun !== null && !stale && !running;

  if (!problem) {
    return (
      <section className="workspace-placeholder">
        <p className="muted">{codeError ?? 'Loading problem…'}</p>
        <button className="ghost" onClick={() => navigate('/problems')}>
          Back to problems
        </button>
      </section>
    );
  }

  return (
    <WorkspacePage
      problem={problem}
      code={code}
      onCodeChange={handleCodeChange}
      onBack={() => navigate('/problems')}
      onRun={handleRun}
      onReview={handleReview}
      running={running}
      reviewing={reviewing}
      canReview={canReview}
      result={lastRun?.result ?? null}
      stale={stale}
      review={review}
      reviewError={reviewError}
      codeLoading={codeLoading}
      codeError={codeError}
    />
  );
}
