import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import SubmissionPage from './SubmissionPage';
import { fetchSubmission } from '../services/api';
import { messageOf } from '../services/errors';
import type { SubmissionDetail } from '../types';

/**
 * Route wrapper for `/history/:submissionId`.
 *
 * A saved run belongs to exactly one student, and the backend scopes the query
 * to the caller — so an id that is not yours comes back as a 404, not as
 * someone else's code. Nothing here needs to enforce that.
 */
export default function SubmissionRoute() {
  const { submissionId } = useParams<{ submissionId: string }>();
  const navigate = useNavigate();

  const id = Number(submissionId);
  const validId = Number.isInteger(id) && id > 0;

  const [submission, setSubmission] = useState<SubmissionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // An unusable id in the URL (e.g. /history/abc) is a dead end; send the
  // student back to the list rather than showing an empty shell.
  useEffect(() => {
    if (!validId) navigate('/history', { replace: true });
  }, [validId, navigate]);

  useEffect(() => {
    if (!validId) return;
    // Guards against a slow response for a run the student has already
    // navigated away from overwriting the current one.
    let cancelled = false;

    setLoading(true);
    setError(null);
    setSubmission(null);

    fetchSubmission(id)
      .then((detail) => {
        if (!cancelled) setSubmission(detail);
      })
      .catch((err) => {
        if (!cancelled) setError(messageOf(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id, validId]);

  if (loading) {
    return (
      <section className="workspace-placeholder">
        <p className="muted">
          <span className="spinner" /> Loading run…
        </p>
      </section>
    );
  }

  if (error || !submission) {
    return (
      <section className="workspace-placeholder">
        <p className="muted">{error ?? 'That run could not be found.'}</p>
        <button className="ghost" onClick={() => navigate('/history')}>
          Back to history
        </button>
      </section>
    );
  }

  return <SubmissionPage submission={submission} />;
}
