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
import type { LanguageSpec, ProblemSummary, Review, RunResult, SaveState } from '../types';

/**
 * How long typing must pause before the draft is written.
 *
 * Long enough that a normal burst of typing produces one request instead of
 * dozens, short enough that the "Draft saved" note appears while the student
 * is still looking at the screen.
 */
const SAVE_DEBOUNCE_MS = 900;

/**
 * The language the workspace opens in when nothing has been chosen yet.
 *
 * Python because it is the language the catalogue is written for and the one
 * every problem's explanation uses.
 */
const FALLBACK_LANGUAGE = 'python';

/**
 * Where the chosen language is remembered, per problem.
 *
 * `localStorage` rather than a column on the server, deliberately: which
 * language you were last looking at is a *view* preference, not part of the
 * student's work, and keeping it here means it survives a refresh without a
 * round trip and works before sign-in too. The draft itself - the code - is
 * still server-side and still per (problem, language).
 */
function languageKey(problemId: number): string {
  return `codereviewer:language:${problemId}`;
}

/**
 * The stored choice, or the fallback.
 *
 * Storage can throw rather than return null: Safari in private mode raises on
 * access, and a browser with site data blocked raises on read. None of that is
 * a reason for the workspace not to load.
 */
function readStoredLanguage(problemId: number): string {
  try {
    return window.localStorage.getItem(languageKey(problemId)) ?? FALLBACK_LANGUAGE;
  } catch {
    return FALLBACK_LANGUAGE;
  }
}

function writeStoredLanguage(problemId: number, language: string): void {
  try {
    window.localStorage.setItem(languageKey(problemId), language);
  } catch {
    // A preference that cannot be persisted is still a preference for this
    // session; there is nothing useful to tell the student about it.
  }
}

/**
 * The stored language if this problem actually offers it, else its first one.
 *
 * A stored choice can outlive the catalogue it was made against - a problem
 * that used to offer JavaScript and no longer does, or a hand-edited storage
 * value. Falling back here means the workspace opens on a language the problem
 * can be run in rather than one that 400s on the first attempt.
 */
function offeredLanguage(offered: string[], preferred: string): string {
  if (offered.includes(preferred)) return preferred;
  return offered[0] ?? FALLBACK_LANGUAGE;
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
    // Nothing was executed, so nothing was recorded either.
    submission_id: null,
    // No container ran, so there are no sandbox facts to report.
    sandbox: null,
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
  // Held separately from `problem` rather than folded into it: the nav-state
  // summary is a `ProblemSummary`, which has no `languages`, so widening the
  // state type to `Problem` would mean lying about what a cold load can render
  // before the fetch resolves.
  const [languages, setLanguages] = useState<Record<string, LanguageSpec>>({});
  const [language, setLanguage] = useState(FALLBACK_LANGUAGE);
  const [code, setCode] = useState('');
  const [codeLoading, setCodeLoading] = useState(true);
  const [codeError, setCodeError] = useState<string | null>(null);

  // Auto-saved draft. `lastSaved` is what the server already has, which is how
  // we avoid writing a row for a problem the student only opened.
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [lastSaved, setLastSaved] = useState('');

  // The language travels with the run, not alongside it: a result is only valid
  // for the code *and* the language it was produced from, and `stale` below is
  // what enforces that.
  const [lastRun, setLastRun] = useState<{ code: string; language: string; result: RunResult } | null>(null);
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

    // The remembered language has to be resolved *before* the draft is
    // fetched, not after: the draft is keyed by language, so asking for the
    // wrong one would hand back another language's code.
    const preferred = readStoredLanguage(id);

    Promise.all([
      fetchProblem(id),
      // A draft is a convenience, never a prerequisite: if this one fails the
      // student still gets the starter code and can work normally.
      fetchSavedCode(id, preferred).catch(() => null),
    ])
      .then(([detail, draft]) => {
        if (cancelled) return;
        // Also fills in the heading on a cold load, where nav state is absent.
        setProblem(detail);
        const offered = Object.keys(detail.languages ?? {});
        const chosen = offeredLanguage(offered, preferred);
        setLanguages(detail.languages ?? {});
        setLanguage(chosen);
        // A problem missing this language has no starter to seed with; an
        // empty editor is a better outcome than a crash or a stale draft.
        const starter = detail.languages?.[chosen]?.starter ?? '';
        const initial = draft?.code ?? starter;
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
  // keystroke. `language` is in here for the same reason it is in the save
  // call: a draft written without it would land in the wrong row.
  const flush = useRef({ id, language, code, lastSaved });
  useEffect(() => {
    flush.current = { id, language, code, lastSaved };
  }, [id, language, code, lastSaved]);

  // The debounce effect clears its timer whenever it re-runs, which includes
  // unmounting - so leaving the workspace would silently drop the last edit.
  // Navigating away inside the app is the common case, so flush it here.
  //
  // Closing the tab outright still risks one debounce interval: the request
  // needs a Bearer header and sendBeacon cannot set one, so there is no
  // reliable unload hook to use instead.
  useEffect(() => {
    return () => {
      const { id: pendingId, language: pendingLanguage, code: pending, lastSaved: saved } = flush.current;
      if (pending && pending !== saved) {
        // Fire and forget: the component is gone, so there is nobody left to
        // tell if this fails.
        void saveCode(pendingId, pending, pendingLanguage).catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    // Nothing to save until the problem has loaded, and never write the
    // untouched starter code.
    if (!validId || codeLoading || !code || code === lastSaved) return;

    const timer = setTimeout(() => {
      setSaveState('saving');
      saveCode(id, code, language)
        .then(() => {
          setLastSaved(code);
          setSaveState('saved');
        })
        .catch(() => setSaveState('error'));
    }, SAVE_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [id, validId, code, codeLoading, lastSaved, language]);

  const handleCodeChange = useCallback((value: string) => {
    setCode(value);
    // A review describes one specific revision, so it is dropped as soon as
    // the code changes rather than silently showing mismatched feedback.
    setReview((current) => (current ? null : current));
  }, []);

  /**
   * Switch the language the student is working in.
   *
   * This is not just a label change: the draft, the starter and the run are all
   * per language, so everything describing the previous attempt is dropped and
   * the editor is re-seeded from the new language's draft or starter. Leaving
   * the old code in place would hand the runner Python source labelled as
   * JavaScript, which is the one outcome that would make the whole selector
   * worse than not having it.
   */
  const handleLanguageChange = useCallback(
    async (next: string) => {
      if (next === language) return;

      writeStoredLanguage(id, next);
      setLanguage(next);
      setLastRun(null);
      setReview(null);
      setReviewError(null);
      setSaveState('idle');
      setLastSaved('');
      setCodeError(null);
      setCodeLoading(true);

      // Deliberately not awaited before `setLanguage`: the selector should
      // respond to the click, not to the round trip. The editor shows its
      // loading state in the meantime, exactly as it does on first open.
      const draft = await fetchSavedCode(id, next).catch(() => null);
      const starter = languages[next]?.starter ?? '';
      const initial = draft?.code ?? starter;
      setCode(initial);
      setLastSaved(initial);
      setCodeLoading(false);
    },
    [id, language, languages],
  );

  const handleRun = useCallback(async () => {
    setRunning(true);
    setReview(null);
    setReviewError(null);
    try {
      const result = await runCode(id, code, language);
      setLastRun({ code, language, result });
    } catch (error) {
      setLastRun({ code, language, result: runFailure(messageOf(error)) });
    } finally {
      setRunning(false);
    }
  }, [id, code, language]);

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

  // A result is stale when either half of its premise has moved: editing the
  // code, or switching language. The second case is why this compares two
  // fields rather than one - a run of Python must not be reviewable as if it
  // were a run of JavaScript.
  const stale = lastRun !== null && (lastRun.code !== code || lastRun.language !== language);
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
      language={language}
      languages={languages}
      onLanguageChange={handleLanguageChange}
    />
  );
}
