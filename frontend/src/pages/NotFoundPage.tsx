import { Link } from 'react-router-dom';

/**
 * Catch-all for unknown paths.
 *
 * Exists because routing made bad URLs reachable for the first time — a typo
 * used to be impossible, since there were no URLs. Without this a mistyped
 * problem id rendered a blank page with no way back.
 */
export default function NotFoundPage() {
  return (
    <main className="state-page">
      <h1>Nothing here</h1>
      <p className="muted">That link does not point at anything in CodeReviewer.</p>
      <Link className="cta" to="/">
        Back to problems
      </Link>
    </main>
  );
}
