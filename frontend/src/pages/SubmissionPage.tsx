import { Link } from 'react-router-dom';

import ReviewPanel from '../components/ReviewPanel';
import TestResults from '../components/TestResults';
import { formatWhen } from '../services/format';
import type { RunResult, SubmissionDetail } from '../types';

type Props = {
  submission: SubmissionDetail;
};

/**
 * One saved run, in full.
 *
 * Read-only, and built from the same two components the workspace uses —
 * `TestResults` and `ReviewPanel` take exactly the shapes the API returns
 * here. Rendering a saved run with a second, separate implementation would
 * have guaranteed that the two drifted, and the history would slowly stop
 * matching what the student actually saw.
 */
export default function SubmissionPage({ submission }: Props) {
  const result: RunResult = {
    status: submission.status,
    passed: submission.passed,
    total: submission.total,
    execution_time: submission.execution_time,
    tests: submission.tests,
    error: submission.error,
    submission_id: submission.id,
    // Sandbox facts are not persisted - they describe the container that ran
    // this submission, which is long gone by the time history is read. The
    // per-case exit code, signal and OOM flag *are* stored with the tests, so
    // the failure itself still reads correctly here.
    sandbox: null,
  };

  return (
    <main className="submission-page">
      <div className="page-head">
        <Link className="back-link" to="/history">
          ← History
        </Link>
        <h1>{submission.problem_title}</h1>
        <p className="muted">
          {submission.problem_difficulty} · {formatWhen(submission.created_at)} ·{' '}
          {submission.language}
        </p>
      </div>

      <div className="submission-actions">
        <Link className="cta" to={`/problems/${submission.problem_id}`}>
          Open in workspace
        </Link>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Submitted code</h2>
        </div>
        <pre className="code-block">
          <code>{submission.code}</code>
        </pre>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Test results</h2>
        </div>
        {/* `stale` is false by definition: this is the exact code that ran. */}
        <TestResults result={result} stale={false} />
      </section>

      {submission.review ? (
        <ReviewPanel review={submission.review} />
      ) : (
        <section className="panel">
          <div className="panel-head">
            <h2>AI review</h2>
          </div>
          <p className="muted panel-note">
            No review was saved for this run. Open it in the workspace to ask for one.
          </p>
        </section>
      )}
    </main>
  );
}
