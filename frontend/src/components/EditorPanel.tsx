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
}: Props) {
  return (
    <section className="editor-panel">
      <div className="editor-head">
        <span>
          <span className="dot" /> main.py
        </span>
        <span>Python 3</span>
      </div>

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
        <button className="review-btn" disabled={!canReview || reviewing} onClick={onReview}>
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
