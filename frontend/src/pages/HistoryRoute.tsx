import { useCallback, useEffect, useState } from 'react';

import HistoryPage from './HistoryPage';
import { fetchSubmissions } from '../services/api';
import { messageOf } from '../services/errors';
import type { SubmissionSummary } from '../types';

/**
 * Route wrapper for `/history`.
 *
 * The whole history arrives in one request. There is no pagination because
 * `GET /api/submissions` caps at 50 by default and this is a single-user
 * academic demo — a pager here would be machinery for a problem that does not
 * exist yet.
 */
export default function HistoryRoute() {
  const [submissions, setSubmissions] = useState<SubmissionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSubmissions(await fetchSubmissions());
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <HistoryPage
      submissions={submissions}
      loading={loading}
      error={error}
      onRetry={load}
    />
  );
}
