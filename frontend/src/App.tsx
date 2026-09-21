import { useCallback, useEffect, useState } from 'react';

import BeamsBackground from './components/BeamsBackground';
import Header from './components/Header';
import LoginPage from './pages/LoginPage';
import ProblemsPage from './pages/ProblemsPage';
import SignUpPage from './pages/SignUpPage';
import WorkspacePage from './pages/WorkspacePage';
import {
  ApiError,
  fetchHealth,
  fetchProblem,
  fetchProblems,
  requestReview,
  runCode,
  toTestResultSummary,
} from './services/api';
import type { ProblemSummary, Review, RunResult } from './types';

type View = 'problems' | 'workspace' | 'login' | 'signup';

/** Turn anything thrown by the API layer into a message we can display. */
function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Please try again.';
}

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
  };
}

export default function App() {
  // --- view routing -----------------------------------------------------
  const [view, setView] = useState<View>('problems');

  // --- problem catalogue ------------------------------------------------
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [loadingProblems, setLoadingProblems] = useState(true);
  const [problemsError, setProblemsError] = useState<string | null>(null);
  const [offlineReview, setOfflineReview] = useState(false);

  // --- active problem ---------------------------------------------------
  const [selected, setSelected] = useState<ProblemSummary | null>(null);
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);

  // --- execution + review ----------------------------------------------
  const [lastRun, setLastRun] = useState<{ code: string; result: RunResult } | null>(null);
  const [running, setRunning] = useState(false);
  const [review, setReview] = useState<Review | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const loadProblems = useCallback(async () => {
    setLoadingProblems(true);
    setProblemsError(null);
    try {
      setProblems(await fetchProblems());
    } catch (error) {
      setProblemsError(messageOf(error));
    } finally {
      setLoadingProblems(false);
    }
  }, []);

  useEffect(() => {
    void loadProblems();
  }, [loadProblems]);

  // Whether reviews come from the model or the rule-based fallback. Purely
  // cosmetic, so a failure here is ignored.
  useEffect(() => {
    fetchHealth()
      .then((health) => setOfflineReview(!health.llm_configured))
      .catch(() => undefined);
  }, []);

  const openProblem = useCallback(async (problem: ProblemSummary) => {
    setView('workspace');
    setSelected(problem);
    setCode('');
    setCodeError(null);
    setLastRun(null);
    setReview(null);
    setReviewError(null);
    setCodeLoading(true);

    try {
      const detail = await fetchProblem(problem.id);
      setCode(detail.starter);
    } catch (error) {
      setCodeError(messageOf(error));
    } finally {
      setCodeLoading(false);
    }
  }, []);

  const goHome = useCallback(() => {
    setView('problems');
    setSelected(null);
    setLastRun(null);
    setReview(null);
    setReviewError(null);
    setCodeError(null);
  }, []);

  const goToSignIn = useCallback(() => setView('login'), []);
  const goToSignUp = useCallback(() => setView('signup'), []);

  const handleCodeChange = useCallback((value: string) => {
    setCode(value);
    // A review describes one specific revision, so it is dropped as soon as
    // the code changes rather than silently showing mismatched feedback.
    setReview((current) => (current ? null : current));
  }, []);

  const handleRun = useCallback(async () => {
    if (!selected) return;
    setRunning(true);
    setReview(null);
    setReviewError(null);
    try {
      const result = await runCode(selected.id, code);
      setLastRun({ code, result });
    } catch (error) {
      setLastRun({ code, result: runFailure(messageOf(error)) });
    } finally {
      setRunning(false);
    }
  }, [selected, code]);

  const handleReview = useCallback(async () => {
    if (!selected || !lastRun) return;
    setReviewing(true);
    setReviewError(null);
    try {
      const result = await requestReview(
        selected.id,
        lastRun.code,
        toTestResultSummary(lastRun.result),
      );
      setReview(result);
    } catch (error) {
      setReviewError(messageOf(error));
    } finally {
      setReviewing(false);
    }
  }, [selected, lastRun]);

  const stale = lastRun !== null && lastRun.code !== code;
  const canReview = lastRun !== null && !stale && !running;

  return (
    <div className="app">
      <BeamsBackground intensity="subtle" />

      <div className="app-content">
        <Header
          onHome={goHome}
          offlineReview={offlineReview}
          onSignIn={goToSignIn}
          onSignUp={goToSignUp}
        />

        {view === 'login' ? (
          <LoginPage
            onBack={goHome}
            onSwitchToSignUp={goToSignUp}
          />
        ) : view === 'signup' ? (
          <SignUpPage
            onBack={goHome}
            onSwitchToSignIn={goToSignIn}
          />
        ) : selected ? (
          <WorkspacePage
            problem={selected}
            code={code}
            onCodeChange={handleCodeChange}
            onBack={goHome}
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
        ) : (
          <ProblemsPage
            problems={problems}
            loading={loadingProblems}
            error={problemsError}
            onSelect={openProblem}
            onRetry={loadProblems}
            onSignUp={goToSignUp}
          />
        )}
      </div>
    </div>
  );
}