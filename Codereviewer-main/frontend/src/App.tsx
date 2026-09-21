import { useCallback, useEffect, useState } from 'react';

import Header from './components/Header';
import ProblemsPage from './pages/ProblemsPage';
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
import type { ProblemSummary, Review, RunResult, SupportedLanguage } from './types';

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

const DEFAULT_LANGUAGE: SupportedLanguage = 'python';

export default function App() {
  // --- problem catalogue ------------------------------------------------
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [loadingProblems, setLoadingProblems] = useState(true);
  const [problemsError, setProblemsError] = useState<string | null>(null);
  const [offlineReview, setOfflineReview] = useState(false);

  // --- active problem ---------------------------------------------------
  const [selected, setSelected] = useState<ProblemSummary | null>(null);
  // Every language's starter code, fetched once per problem so switching
  // languages is instant and doesn't re-hit the API.
  const [starters, setStarters] = useState<Partial<Record<SupportedLanguage, string>>>({});
  const [language, setLanguage] = useState<SupportedLanguage>(DEFAULT_LANGUAGE);
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);

  // --- execution + review ----------------------------------------------
  const [lastRun, setLastRun] = useState<{
    code: string;
    language: SupportedLanguage;
    result: RunResult;
  } | null>(null);
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
    // Switch screens immediately using the list data, then fetch the starter
    // code in the background so the transition feels instant. Language
    // always resets to the default when opening a fresh problem.
    setSelected(problem);
    setLanguage(DEFAULT_LANGUAGE);
    setStarters({});
    setCode('');
    setCodeError(null);
    setLastRun(null);
    setReview(null);
    setReviewError(null);
    setCodeLoading(true);

    try {
      const detail = await fetchProblem(problem.id);
      setStarters(detail.starter);
      setCode(detail.starter[DEFAULT_LANGUAGE] ?? Object.values(detail.starter)[0] ?? '');
    } catch (error) {
      setCodeError(messageOf(error));
    } finally {
      setCodeLoading(false);
    }
  }, []);

  const goHome = useCallback(() => {
    setSelected(null);
    setLastRun(null);
    setReview(null);
    setReviewError(null);
    setCodeError(null);
  }, []);

  const handleCodeChange = useCallback((value: string) => {
    setCode(value);
    // A review describes one specific revision, so it is dropped as soon as
    // the code changes rather than silently showing mismatched feedback.
    setReview((current) => (current ? null : current));
  }, []);

  const handleLanguageChange = useCallback(
    (next: SupportedLanguage) => {
      // The editor holds one language's code at a time, so switching
      // languages loads that language's starter template. Any run result or
      // review was for the previous language's code, so it's cleared too.
      setLanguage(next);
      setCode(starters[next] ?? '');
      setLastRun(null);
      setReview(null);
      setReviewError(null);
    },
    [starters],
  );

  const handleRun = useCallback(async () => {
    if (!selected) return;
    setRunning(true);
    setReview(null);
    setReviewError(null);
    try {
      const result = await runCode(selected.id, code, language);
      setLastRun({ code, language, result });
    } catch (error) {
      setLastRun({ code, language, result: runFailure(messageOf(error)) });
    } finally {
      setRunning(false);
    }
  }, [selected, code, language]);

  const handleReview = useCallback(async () => {
    if (!selected || !lastRun) return;
    setReviewing(true);
    setReviewError(null);
    try {
      // Review the code that was actually executed, so the feedback and the
      // test results can never disagree.
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

  const stale = lastRun !== null && (lastRun.code !== code || lastRun.language !== language);
  const canReview = lastRun !== null && !stale && !running;

  return (
    <div className="app">
      <Header onHome={goHome} offlineReview={offlineReview} language={selected ? language : undefined} />

      {selected ? (
        <WorkspacePage
          problem={selected}
          code={code}
          onCodeChange={handleCodeChange}
          language={language}
          onLanguageChange={handleLanguageChange}
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
        />
      )}
    </div>
  );
}
