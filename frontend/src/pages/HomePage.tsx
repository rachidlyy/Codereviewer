import { useMemo } from 'react';
import type { CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CircleAlert } from 'lucide-react';

import type { ProblemProgress, Progress } from '../types';

type Props = {
  /** The student's first name from Clerk, when it is available. */
  name: string | null;
  progress: Progress | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
};

/** A bar showing how much of a problem's test suite the student has reached. */
function bestPercent(problem: ProblemProgress): number {
  if (problem.total_tests <= 0) return 0;
  return Math.round((problem.best_passed / problem.total_tests) * 100);
}

/**
 * One problem, as a row that links into the workspace.
 *
 * Used for both the "continue" row and the "up next" list, which differ only in
 * the wording of the call to action and in `lead`. The continue row is the
 * page's primary action, so it carries the surface and the accent edge; the
 * rows under "up next" stay quiet.
 */
function ProblemRow({
  problem,
  cta,
  lead = false,
}: {
  problem: ProblemProgress;
  cta: string;
  lead?: boolean;
}) {
  const percent = bestPercent(problem);
  const passed = problem.total_tests > 0 ? `${problem.best_passed}/${problem.total_tests}` : '—';

  return (
    <Link
      className={lead ? 'problem-row is-lead' : 'problem-row'}
      to={`/problems/${problem.problem_id}`}
    >
      <span className="problem-row-main">
        <b>{problem.title}</b>
        {/* `best x/y` used to sit here as well as on the bar. The figure beside
            the bar is the same number, so this line keeps only the meta the bar
            cannot carry. */}
        <small>
          {problem.difficulty}
          {problem.attempted
            ? ` · ${problem.attempts} ${problem.attempts === 1 ? 'run' : 'runs'}`
            : ' · not attempted yet'}
        </small>
      </span>

      <span className="problem-row-progress">
        {/* The bar is decoration; the figure beside it carries the value as
            text, so nothing here needs announcing. `--fill` drives a scaleX
            transform — animating width would relayout on every frame. */}
        <span className="problem-row-bar" aria-hidden="true">
          <i style={{ '--fill': percent / 100 } as CSSProperties} />
        </span>
        <b>{passed}</b>
      </span>

      <span className="problem-row-cta">
        {cta}
        <ArrowRight size={14} />
      </span>
    </Link>
  );
}

/**
 * The signed-in home page.
 *
 * Built around one question — "what should I do now?" — rather than a summary
 * of the past. That is why it leads with the problems the student has done
 * *least*, and why `GET /api/progress` returns the whole catalogue instead of
 * only the attempted problems: a dashboard that can only describe work already
 * done has nothing to say to someone opening the app for the first time.
 *
 * Composed as one centred column. The figures, the section headings and the
 * rows all share its left edge, and each section carries exactly one level of
 * card depth — the list is the card, the heading sits on the page.
 */
export default function HomePage({ name, progress, loading, error, onRetry }: Props) {
  const problems = progress?.problems ?? [];

  const upNext = useMemo(
    () =>
      problems
        // `.filter` already returns a new array, so sorting it is safe.
        .filter((problem) => !problem.solved)
        // Fewest attempts first, so a barely-touched problem comes up before
        // one the student has already ground through. `problem_id` breaks the
        // tie, keeping the order stable between renders.
        .sort((a, b) => a.attempts - b.attempts || a.problem_id - b.problem_id)
        .slice(0, 3),
    [problems],
  );

  const lastTouched = useMemo(() => {
    const attempted = problems.filter((problem) => problem.last_attempt_at !== null);
    if (attempted.length === 0) return null;
    // ISO timestamps sort lexicographically, so a plain string compare finds
    // the most recent one without parsing every date.
    return attempted.reduce((best, problem) =>
      (problem.last_attempt_at as string) > (best.last_attempt_at as string) ? problem : best,
    );
  }, [problems]);

  return (
    <main className="home-page">
      <div className="page-head">
        <h1>{name ? `Welcome back, ${name}` : 'Your progress'}</h1>
        <p className="muted">
          {loading
            ? 'Loading your progress…'
            : progress
              ? `${progress.solved_problems} of ${progress.total_problems} problems solved.`
              : 'Pick up where you left off.'}
        </p>
      </div>

      {!loading && error && (
        <div className="state-panel state-error">
          <CircleAlert size={20} />
          <div>
            <b>Could not load your progress</b>
            <p>{error}</p>
          </div>
          <button className="retry" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {loading && !progress && (
        <div className="state-panel">
          <span className="spinner" /> Loading your progress…
        </div>
      )}

      {progress && (
        <>
          {/* Was four bordered tiles with centred text. One band reads as a
              single set of figures rather than four competing cards, and the
              numbers sit on the column's left edge like everything else. */}
          <section className="stat-band" aria-label="Your progress at a glance">
            <div className="stat">
              <b>
                {progress.solved_problems}
                <span>/{progress.total_problems}</span>
              </b>
              <small>Solved</small>
            </div>
            <div className="stat">
              <b>{progress.attempted_problems}</b>
              <small>Attempted</small>
            </div>
            <div className="stat">
              <b>{progress.total_submissions}</b>
              <small>Runs</small>
            </div>
            <div className="stat">
              <b>
                {progress.average_score === null ? '—' : progress.average_score.toFixed(1)}
                {progress.average_score === null ? null : <span>/10</span>}
              </b>
              <small>Average review</small>
            </div>
          </section>

          {lastTouched && (
            <section className="home-section">
              <div className="home-section-head">
                <h2>Pick up where you left off</h2>
              </div>
              <ProblemRow problem={lastTouched} cta="Continue" lead />
            </section>
          )}

          <section className="home-section">
            <div className="home-section-head">
              <h2>{lastTouched ? 'Up next' : 'Start here'}</h2>
              <Link className="ghost" to="/problems">
                All problems
              </Link>
            </div>

            {upNext.length === 0 ? (
              <p className="muted panel-note">
                Every problem is solved.{' '}
                <Link to="/history">Look back at your history</Link> to see how you got there.
              </p>
            ) : (
              <ul className="problem-rows">
                {upNext.map((problem) => (
                  <li key={problem.problem_id}>
                    <ProblemRow problem={problem} cta={problem.attempted ? 'Resume' : 'Start'} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <p className="home-foot muted">
            <Link to="/history">Submission history</Link>
          </p>
        </>
      )}
    </main>
  );
}
