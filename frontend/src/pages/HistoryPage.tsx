import { Link } from 'react-router-dom';
import { CircleAlert, History } from 'lucide-react';

import { formatWhen } from '../services/format';
import type { RunStatus, SubmissionSummary } from '../types';

type Props = {
  submissions: SubmissionSummary[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
};

const STATUS_LABEL: Record<RunStatus, string> = {
  passed: 'Passed',
  partial: 'Partial',
  failed: 'Failed',
  error: 'Error',
  timeout: 'Timed out',
};

/**
 * The student's run history, newest first.
 *
 * Every row links to the saved run rather than expanding in place. A history
 * list that cannot be opened is just a log — the point of keeping the code and
 * the review is being able to go back and read them.
 */
export default function HistoryPage({ submissions, loading, error, onRetry }: Props) {
  return (
    <main className="history-page">
      <div className="page-head">
        <h1>History</h1>
        <p className="muted">
          {loading
            ? 'Loading your runs…'
            : submissions.length === 0
              ? 'Every run you make is saved here.'
              : `${submissions.length} saved ${submissions.length === 1 ? 'run' : 'runs'}, newest first.`}
        </p>
      </div>

      {loading && (
        <div className="state-panel">
          <span className="spinner" /> Loading your runs…
        </div>
      )}

      {!loading && error && (
        <div className="state-panel state-error">
          <CircleAlert size={20} />
          <div>
            <b>Could not load your history</b>
            <p>{error}</p>
          </div>
          <button className="retry" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {!loading && !error && submissions.length === 0 && (
        <div className="state-panel">
          <History size={20} />
          <div>
            <b>No runs yet</b>
            <p>
              Run a problem and it will show up here, along with the review if you ask for one.
            </p>
          </div>
          <Link className="cta" to="/problems">
            Browse problems
          </Link>
        </div>
      )}

      {!loading && !error && submissions.length > 0 && (
        <ul className="history-list">
          {submissions.map((submission) => (
            <li key={submission.id}>
              <Link className="history-row" to={`/history/${submission.id}`}>
                <div className="history-main">
                  <b>{submission.problem_title}</b>
                  <small>
                    {submission.problem_difficulty} · {formatWhen(submission.created_at)}
                  </small>
                </div>

                <span className={`status ${submission.status}`}>
                  {STATUS_LABEL[submission.status]}
                </span>

                <span className="history-tests">
                  {submission.passed}/{submission.total} tests
                </span>

                {/* A run with no review is normal, not a gap to apologise for,
                    so this reads as a dash rather than an error. */}
                <span
                  className={
                    submission.overall_score === null
                      ? 'history-score empty'
                      : 'history-score'
                  }
                  title={
                    submission.review_source === 'heuristic'
                      ? 'Rule-based review (no LLM key configured)'
                      : undefined
                  }
                >
                  {submission.overall_score === null
                    ? '—'
                    : `${submission.overall_score}/10`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
