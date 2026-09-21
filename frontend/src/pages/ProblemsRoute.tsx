import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import ProblemsPage from './ProblemsPage';
import { fetchProblems } from '../services/api';
import { messageOf } from '../services/errors';
import type { ProblemSummary } from '../types';

/**
 * Route wrapper for the problem catalogue.
 *
 * Owns the catalogue fetch so `ProblemsPage` stays presentational. Selecting a
 * problem navigates rather than setting local state, which is what makes the
 * workspace linkable and the browser Back button work.
 */
export default function ProblemsRoute() {
  const navigate = useNavigate();
  const [problems, setProblems] = useState<ProblemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProblems(await fetchProblems());
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
    <ProblemsPage
      problems={problems}
      loading={loading}
      error={error}
      // The row we already have travels with the navigation, so the workspace
      // can render its heading immediately instead of flashing empty while it
      // fetches the starter code.
      onSelect={(problem) => navigate(`/problems/${problem.id}`, { state: { summary: problem } })}
      onRetry={load}
    />
  );
}
