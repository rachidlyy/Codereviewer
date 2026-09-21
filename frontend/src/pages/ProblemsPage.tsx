import { useMemo, useState } from 'react';
import { CircleAlert, Filter, Search } from 'lucide-react';

import ProblemCard from '../components/ProblemCard';
import type { ProblemSummary } from '../types';

type Props = {
  problems: ProblemSummary[];
  loading: boolean;
  error: string | null;
  onSelect: (problem: ProblemSummary) => void;
  onRetry: () => void;
};

/**
 * The full catalogue.
 *
 * The hero and the four-step explainer used to live at the top of this file.
 * They moved to `components/LandingHero.tsx` when `/` became the home page and
 * `/problems` became the catalogue: a student who has already signed in and is
 * looking for a specific problem does not need to be pitched to first.
 */
export default function ProblemsPage({ problems, loading, error, onSelect, onRetry }: Props) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('All');

  // Derive the difficulty filters from the data rather than hardcoding them,
  // so adding a "Hard" problem later needs no change here.
  const filters = useMemo(() => {
    const difficulties = Array.from(new Set(problems.map((p) => p.difficulty)));
    return ['All', ...difficulties];
  }, [problems]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return problems.filter((problem) => {
      if (filter !== 'All' && problem.difficulty !== filter) return false;
      if (!needle) return true;
      const haystack = `${problem.title} ${problem.category} ${problem.tags.join(' ')}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [problems, filter, query]);

  return (
    <main className="problems-page">
      <section className="catalogue" id="catalogue">
        <div className="page-head">
          <h1>Problems</h1>
          <p className="muted">
            {loading
              ? 'Loading…'
              : `${problems.length} challenges, Python only. Sign in to keep your history.`}
          </p>
        </div>

        <div className="toolbar">
          <div className="search">
            <Search size={17} />
            <input
              placeholder="Search problems..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="filters">
            <Filter size={15} />
            {filters.map((option) => (
              <button
                className={filter === option ? 'active' : ''}
                onClick={() => setFilter(option)}
                key={option}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="section-title">
          <h2>Choose a challenge</h2>
          <small>{loading ? 'Loading…' : `${filtered.length} problems`}</small>
        </div>

        {loading && (
          <div className="state-panel">
            <span className="spinner" /> Loading problems…
          </div>
        )}

        {!loading && error && (
          <div className="state-panel state-error">
            <CircleAlert size={20} />
            <div>
              <b>Could not load problems</b>
              <p>{error}</p>
            </div>
            <button className="retry" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="state-panel">
            No problems match “{query}”. Try a different search or filter.
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid">
            {filtered.map((problem) => (
              <ProblemCard problem={problem} onSelect={onSelect} key={problem.id} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
