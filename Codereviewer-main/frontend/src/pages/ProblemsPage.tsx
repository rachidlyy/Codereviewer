import { useMemo, useState } from 'react';
import { ChevronRight, CircleAlert, Filter, Search } from 'lucide-react';

import ProblemCard from '../components/ProblemCard';
import type { ProblemSummary } from '../types';

type Props = {
  problems: ProblemSummary[];
  loading: boolean;
  error: string | null;
  onSelect: (problem: ProblemSummary) => void;
  onRetry: () => void;
};

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
      <section className="hero">
        <div>
          <p className="eyebrow">CODING PRACTICE + AI REVIEW</p>
          <h1>
            Sharpen your code.
            <br />
            <span>Understand why it works.</span>
          </h1>
          <p className="hero-copy">
            Solve focused coding problems, run real test cases, and get actionable feedback from an
            AI programming mentor.
          </p>
        </div>
        <div className="flow">
          <div>PROBLEM</div>
          <ChevronRight />
          <div>CODE</div>
          <ChevronRight />
          <div>TEST</div>
          <ChevronRight />
          <div>REVIEW</div>
        </div>
      </section>

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
        <div>
          <span>PROBLEMS</span>
          <h2>Choose a challenge</h2>
        </div>
        <small>{loading ? 'Loading…' : `${filtered.length} problems`}</small>
      </div>

      {loading && <div className="state-panel">Loading problems…</div>}

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
    </main>
  );
}
