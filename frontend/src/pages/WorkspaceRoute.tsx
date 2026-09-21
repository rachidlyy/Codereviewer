import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import WorkspacePage from './WorkspacePage';
import {
  fetchProblem,
  fetchSavedCode,
  requestReview,
  runCode,
  saveCode,
  toTestResultSummary,
} from '../services/api';
import { messageOf } from '../services/errors';
import type { ProblemSummary, Review, RunResult, SaveState } from '../types';

/**
 * How long typing must pause before the draft is written.
 *
 * Long enough that a normal burst of typing produces one request instead of
 * dozens, short enough that the "Draft saved" note appears while the student
 * is still looking at the screen.
 */
const SAVE_DEBOUNCE_MS = 900;

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

  // Auto-saved draft. `lastSaved` is what the server already has, which is how
  // we avoid writing a row for a problem the student only opened.
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [lastSaved, setLastSaved] = useState('');

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
    setSaveState('idle');
    setLastSaved('');

    Promise.all([
      fetchProblem(id),
      // A draft is a convenience, never a prerequisite: if this one fails the
      // student still gets the starter code and can work normally.
      fetchSavedCode(id).catch(() => null),
    ])
      .then(([detail, draft]) => {
        if (cancelled) return;
        // Also fills in the heading on a cold load, where nav state is absent.
        setProblem(detail);
        const initial = draft?.code ?? detail.starter;
        setCode(initial);
        // Whatever we loaded counts as already saved, so simply opening a
        // problem never writes a row.
        setLastSaved(initial);
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

  // Mirrors of the live values, so the unmount flush below can read them
  // without the effect that owns the debounce timer being rebuilt on every
  // keystroke.
  const flush = useRef({ id, code, lastSaved });
  useEffect(() => {
    flush.current = { id, code, lastSaved };
  }, [id, code, lastSaved]);

  // The debounce effect clears its timer whenever it re-runs, which includes
  // unmounting - so leaving the workspace would silently drop the last edit.
  // Navigating away inside the app is the common case, so flush it here.
  //
  // Closing the tab outright still risks one debounce interval: the request
  // needs a Bearer header and sendBeacon cannot set one, so there is no
  // reliable unload hook to use instead.
  useEffect(() => {
    return () => {
      const { id: pendingId, code: pending, lastSaved: saved } = flush.current;
      if (pending && pending !== saved) {
        // Fire and forget: the component is gone, so there is nobody left to
        // tell if this fails.
        void saveCode(pendingId, pending).catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    // Nothing to save until the problem has loaded, and never write the
    // untouched starter code.
    if (!validId || codeLoading || !code || code === lastSaved) return;

    const timer = setTimeout(() => {
      setSaveState('saving');
      saveCode(id, code)
        .then(() => {
          setLastSaved(code);
          setSaveState('saved');
        })
        .catch(() => setSaveState('error'));
    }, SAVE_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [id, validId, code, codeLoading, lastSaved]);

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
      saveState={saveState}
    />
  );
}
