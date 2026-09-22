import { ArrowLeft, CircleAlert } from 'lucide-react';

import EditorPanel from '../components/EditorPanel';
import ProblemPanel from '../components/ProblemPanel';
import ReviewPanel from '../components/ReviewPanel';
import type { LanguageSpec, ProblemSummary, Review, RunResult, SaveState } from '../types';

type Props = {
  problem: ProblemSummary;
  code: string;
  onCodeChange: (code: string) => void;
  onBack: () => void;
  onRun: () => void;
  onReview: () => void;
  running: boolean;
  reviewing: boolean;
  canReview: boolean;
  result: RunResult | null;
  stale: boolean;
  review: Review | null;
  reviewError: string | null;
  codeLoading: boolean;
  codeError: string | null;
  /** Auto-save status of the working draft. */
  saveState: SaveState;
  /** The language the student is working in, and the ones this problem offers. */
  language: string;
  languages: Record<string, LanguageSpec>;
  onLanguageChange: (language: string) => void;
};

export default function WorkspacePage({
  problem,
  code,
  onCodeChange,
  onBack,
  onRun,
  onReview,
  running,
  reviewing,
  canReview,
  result,
  stale,
  review,
  reviewError,
  codeLoading,
  codeError,
  saveState,
  language,
  languages,
  onLanguageChange,
}: Props) {
  return (
    <main className="workspace">
      <div className="workbench-bar">
        <button className="back" onClick={onBack}>
          <ArrowLeft size={16} /> All problems
        </button>
        <span className="workbench-meta">
          {problem.category} · Problem {problem.id}
        </span>
      </div>

      <div className="workspace-head">
        <h1>{problem.title}</h1>
        <span className={'difficulty ' + problem.difficulty.toLowerCase()}>
          {problem.difficulty}
        </span>
      </div>

      {codeError && (
        <div className="error workspace-error">
          <CircleAlert size={17} />
          <div>
            <b>Could not load the starter code</b>
            <p>{codeError}</p>
          </div>
        </div>
      )}

      {/* Workbench: a sticky brief rail beside one working column. The review
          sits inside that column rather than below the whole grid, so
          run -> test results -> review reads as a single downward flow instead
          of three panels that happen to be on the same screen. */}
      <div className="workspace-grid">
        <ProblemPanel problem={problem} />
        <div className="work-col">
          <EditorPanel
            code={code}
            onCodeChange={onCodeChange}
            onRun={onRun}
            onReview={onReview}
            running={running}
            reviewing={reviewing}
            canReview={canReview}
            result={result}
            stale={stale}
            reviewError={reviewError}
            loading={codeLoading}
            saveState={saveState}
            language={language}
            languages={languages}
            onLanguageChange={onLanguageChange}
          />
          {review && <ReviewPanel review={review} />}
        </div>
      </div>
    </main>
  );
}
