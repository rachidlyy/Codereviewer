import Editor from '@monaco-editor/react';
import { ChevronDown, CircleAlert, Play, Sparkles } from 'lucide-react';

import TestResults from './TestResults';
import type { LanguageSpec, RunResult, SaveState } from '../types';

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
  /** Auto-save status of the draft. `idle` renders nothing. */
  saveState: SaveState;
  /** The language currently selected, e.g. `python`. */
  language: string;
  /** Every language this problem offers, as returned by the problem detail. */
  languages: Record<string, LanguageSpec>;
  onLanguageChange: (language: string) => void;
};

/** Wording for the auto-save chip. `idle` is deliberately absent: it shows nothing. */
const SAVE_LABEL: Record<Exclude<SaveState, 'idle'>, string> = {
  saving: 'Saving…',
  saved: 'Draft saved',
  error: 'Draft not saved',
};

/**
 * How each language is presented in the editor chrome.
 *
 * A display table rather than fields on `LanguageSpec`, because none of this is
 * a fact the *server* owns: Monaco's language id and the conventional filename
 * are editor concerns, and putting them in the API would mean a backend change
 * every time the editor's conventions moved.
 *
 * The filename is cosmetic today - student code is executed from a string, not
 * a file - but a tab reading `main.py` while the editor contains JavaScript is
 * exactly the kind of small lie that makes a demo feel unfinished.
 */
const LANGUAGE_DISPLAY: Record<string, { label: string; monaco: string; file: string }> = {
  python: { label: 'Python 3', monaco: 'python', file: 'main.py' },
  javascript: { label: 'JavaScript', monaco: 'javascript', file: 'main.js' },
};

/** Falls back to the raw id so an unmapped language degrades rather than crashes. */
function displayOf(language: string): { label: string; monaco: string; file: string } {
  return LANGUAGE_DISPLAY[language] ?? { label: language, monaco: 'plaintext', file: `main.${language}` };
}

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
  saveState,
  language,
  languages,
  onLanguageChange,
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

  const offered = Object.keys(languages);
  const current = displayOf(language);
  // Switching language mid-run would discard the run, so it is blocked while
  // one is in flight or the starter is still loading. Computed once because it
  // drives both the `disabled` attribute and the wrapper's class: the opacity
  // has to sit on the wrapper, not on the `<select>`, or the chevron beside it
  // would stay bright while the label dimmed.
  const languageLocked = loading || running;

  return (
    <section className="editor-panel">
      <div className="editor-head">
        <span>
          <span className="dot" /> {current.file}
        </span>
        <span className="editor-head-meta">
          {/* Auto-save status. Rendered only when there is something to say,
              so the chip never holds empty space while nothing is happening. */}
          {saveState !== 'idle' && (
            <span className={'save-state ' + saveState}>{SAVE_LABEL[saveState]}</span>
          )}
          {/* A selector only when there is a choice to make. With one language
              the label is the honest rendering; a control with a single option
              is just a worse label.

              A native `<select>` rather than a custom popover, which is why
              this is so little code: the page sets `color-scheme: dark`, so the
              option list the OS draws is already dark, and keyboard handling,
              focus management and screen-reader support come for free. A custom
              menu would be a worse version of all three. */}
          {offered.length > 1 ? (
            <span className={'language-select' + (languageLocked ? ' is-locked' : '')}>
              <select
                value={language}
                onChange={(event) => onLanguageChange(event.target.value)}
                disabled={languageLocked}
                aria-label="Language"
              >
                {offered.map((name) => (
                  <option key={name} value={name}>
                    {displayOf(name).label}
                  </option>
                ))}
              </select>
              {/* Decorative. The stylesheet sets `pointer-events:none` on it so
                  a click on the chevron reaches the select underneath. */}
              <ChevronDown size={13} aria-hidden="true" />
            </span>
          ) : (
            <span>{current.label}</span>
          )}
        </span>
      </div>

      <div className="editor-wrap">
        <Editor
          height="490px"
          language={current.monaco}
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
