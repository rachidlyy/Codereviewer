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
 * The languages the catalogue is offered in, as a single sentence.
 *
 * Deliberately a constant rather than derived from the response. The list
 * projection is kept lean on purpose - it carries no starter code and no
 * signature, and `check_runner` section 9 asserts that - so the language names
 * are not in it. Adding them just for this sentence would widen every catalogue
 * response to save one string. Phase 6 adds Java and C++ and will have to touch
 * this line, which is the honest cost of that choice.
 */
const OFFERED_LANGUAGES = 'Python and JavaScript';

/**
 * The full catalogue.
 *
 * The hero and the four-step explainer used to live at the top of this file.
 * They moved to `components/LandingHero.tsx` when `/` became the home page and
 * `/problems` became the catalogue: a student who has already signed in and is
 * looking for a specific problem does not need to be pitched to first.
 *
 * Two independent filters rather than one merged list. Difficulty and category
 * answer different questions ("how hard?" and "what kind of problem?"), and a
 * student who has just learned about stacks wants to narrow by *that* without
 * also being forced to pick a difficulty. Merging them into one row of chips
 * would make the second question unaskable.
 */
export default function ProblemsPage({ problems, loading, error, onSelect, onRetry }: Props) {
  const [query, setQuery] = useState('');
  const [difficulty, setDifficulty] = useState('All');
  const [category, setCategory] = useState('All');

  // Derive both axes from the data rather than hardcoding them, so adding a
  // "Hard" problem or a new category needs no change here.
  const difficultyOptions = useMemo(() => {
    const found = Array.from(new Set(problems.map((p) => p.difficulty)));
    // Easy -> Medium -> Hard rather than whatever order the catalogue happens
    // to be in, because that is the order a student reads them in.
    const rank = ['Easy', 'Medium', 'Hard'];
    found.sort((a, b) => {
      const left = rank.indexOf(a);
      const right = rank.indexOf(b);
      if (left === -1 && right === -1) return a.localeCompare(b);
      if (left === -1) return 1;
      if (right === -1) return -1;
      return left - right;
    });
    return ['All', ...found];
  }, [problems]);

  const categoryOptions = useMemo(() => {
    const found = Array.from(new Set(problems.map((p) => p.category))).sort();
    return ['All', ...found];
  }, [problems]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return problems.filter((problem) => {
      if (difficulty !== 'All' && problem.difficulty !== difficulty) return false;
      if (category !== 'All' && problem.category !== category) return false;
      if (!needle) return true;
      const haystack = `${problem.title} ${problem.category} ${problem.tags.join(' ')}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [problems, difficulty, category, query]);

  const narrowed = difficulty !== 'All' || category !== 'All' || query.trim() !== '';

  return (
    <main className="problems-page">
      <section className="catalogue" id="catalogue">
        <div className="page-head">
          <h1>Problems</h1>
          <p className="muted">
            {loading
              ? 'Loading…'
              : `${problems.length} challenges in ${OFFERED_LANGUAGES}. Sign in to keep your history.`}
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
          <div className="filter-stack">
            <div className="filters">
              <Filter size={15} />
              <span className="filters-label">Difficulty</span>
              {difficultyOptions.map((option) => (
                <button
                  className={difficulty === option ? 'active' : ''}
                  onClick={() => setDifficulty(option)}
                  key={option}
                >
                  {option}
                </button>
              ))}
            </div>
            <div className="filters">
              <Filter size={15} />
              <span className="filters-label">Category</span>
              {categoryOptions.map((option) => (
                <button
                  className={category === option ? 'active' : ''}
                  onClick={() => setCategory(option)}
                  key={option}
                >
                  {option}
                </button>
              ))}
            </div>
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
            {/* Names the thing that is actually narrowing the list: "no problems
                match your search" is wrong when the search box is empty and a
                filter is doing the excluding. */}
            No problems match {query.trim() ? `“${query}”` : 'these filters'}. Try a different
            search or filter.
            {narrowed && (
              <>
                {' '}
                <button
                  className="ghost"
                  onClick={() => {
                    setQuery('');
                    setDifficulty('All');
                    setCategory('All');
                  }}
                >
                  Clear filters
                </button>
              </>
            )}
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
