import { ArrowLeft, CircleAlert } from 'lucide-react';

import EditorPanel from '../components/EditorPanel';
import ProblemPanel from '../components/ProblemPanel';
import ReviewPanel from '../components/ReviewPanel';
import type { ProblemSummary, Review, RunResult } from '../types';

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
}: Props) {
  return (
    <main className="workspace">
      <button className="back" onClick={onBack}>
        <ArrowLeft size={16} /> All problems
      </button>

      <div className="workspace-head">
        <div>
          <p className="eyebrow">
            {problem.category.toUpperCase()} / PROBLEM {problem.id}
          </p>
          <h1>{problem.title}</h1>
        </div>
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

      <div className="workspace-grid">
        <ProblemPanel problem={problem} />
        <EditorPanel
          code={codeLoading ? '# Loading starter code…' : code}
          onCodeChange={onCodeChange}
          onRun={onRun}
          onReview={onReview}
          running={running}
          reviewing={reviewing}
          canReview={canReview}
          result={result}
          stale={stale}
          reviewError={reviewError}
        />
      </div>

      {review && <ReviewPanel review={review} />}
    </main>
  );
}
