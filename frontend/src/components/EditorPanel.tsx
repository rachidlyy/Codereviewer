import Editor from '@monaco-editor/react';
import { CircleAlert, Play, Sparkles } from 'lucide-react';

import TestResults from './TestResults';
import type { RunResult } from '../types';

type Props = {
  code: string;
  onCodeChange: (code: string) => void;
  onRun: () => void;
  onReview: () => void;
  running: boolean;
  reviewing: boolean;
  /** The review button stays disabled until a run has produced results. */
  canReview: boolean;
  result: RunResult | null;
  stale: boolean;
  reviewError: string | null;
  /** The starter code is still being fetched. */
  loading: boolean;
};

export default function EditorPanel({
  code,
  onCodeChange,
  onRun,
  onReview,
  running,
  reviewing,
  canReview,
  result,
  stale,
  reviewError,
  loading,
}: Props) {
  // A disabled button gives no reason for being disabled, and "run your code
  // first" is the one rule of this screen that isn't obvious from the layout.
  const reviewTitle = reviewing
    ? undefined
    : canReview
      ? undefined
      : stale
        ? 'Your code changed since the last run — run it again before reviewing'
        : 'Run your code first — the review is based on your test results';

  return (
    <section className="editor-panel">
      <div className="editor-head">
        <span>
          <span className="dot" /> main.py
        </span>
        <span>Python 3</span>
      </div>

      <div className="editor-wrap">
        <Editor
          height="490px"
          language="python"
          theme="vs-dark"
          value={code}
          onChange={(value) => onCodeChange(value ?? '')}
          options={{
            fontSize: 14,
            minimap: { enabled: false },
            padding: { top: 18 },
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
        />
        {loading && (
          <div className="editor-loading">
            <span className="spinner" /> Loading starter code…
          </div>
        )}
      </div>

      <div className="action-bar">
        <button className="run" onClick={onRun} disabled={running}>
          {running ? (
            <>
              <span className="spinner" /> Running...
            </>
          ) : (
            <>
              <Play size={15} fill="currentColor" /> Run Code
            </>
          )}
        </button>
        <button
          className="review-btn"
          disabled={!canReview || reviewing}
          onClick={onReview}
          title={reviewTitle}
        >
          {reviewing ? (
            <>
              <span className="spinner" /> Reviewing...
            </>
          ) : (
            <>
              <Sparkles size={16} /> Get AI Review
            </>
          )}
        </button>
      </div>

      {reviewError && (
        <div className="error review-error">
          <CircleAlert size={17} />
          <div>
            <b>{reviewError}</b>
            <p>Your code and test results are still here — nothing was lost.</p>
          </div>
        </div>
      )}

      <TestResults result={result} stale={stale} />
    </section>
  );
}
