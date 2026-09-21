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
  onSignUp: () => void;   // ← new
};

/** The four stages of the loop the whole product is built around. This is the
 *  feature stack: it explains the demo path rather than listing generic
 *  capabilities, which is the honest version of "what does this do". */
const STEPS = [
  {
    name: 'Problem',
    body: 'Pick a focused challenge with a written brief and worked examples.',
  },
  {
    name: 'Code',
    body: 'Write Python in a real editor, with starter code already in place.',
  },
  {
    name: 'Test',
    body: 'Run the actual test suite and see exactly which cases pass.',
  },
  {
    name: 'Review',
    body: 'Get scored feedback on correctness, readability and efficiency.',
  },
];

/** Static sample data for the hero proof panel. Deliberately illustrative, and
 *  labelled as such - it previews the real review output rather than inventing
 *  a screenshot of a run that never happened. */
const SAMPLE_SCORES = [
  { label: 'Correctness', value: 9 },
  { label: 'Readability', value: 8 },
  { label: 'Efficiency', value: 7 },
];

export default function ProblemsPage({
  problems,
  loading,
  error,
  onSelect,
  onRetry,
  onSignUp,
}: Props) {
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
      {/* Hero. Sized to complete inside the first viewport: headline,
          supporting line, CTA and proof panel all sit above the fold. */}
     
      <section className="hero">
     

        <h1>
          Sharpen your code.
          <br />
          <span>Understand why it works.</span>
        </h1>
        <p className="hero-copy">
          Solve focused coding problems, run real test cases, and get actionable feedback from an AI
          programming mentor.
        </p>
        <div className="hero-actions">
          <a className="cta" href="#catalogue">
            Browse problems
          </a>
          <span className="cta-note">No account, no setup — pick one and run it.</span>
<button className="cta" type="button" onClick={onSignUp}>
  Create account
</button>
        </div>

        <figure className="hero-proof">
          <div className="proof-head">
            <span>Sample AI review</span>
            <span className="proof-score">
              8<span>/10</span>
            </span>
          </div>
          <div className="proof-bars">
            {SAMPLE_SCORES.map((score) => (
              <div className="proof-bar" key={score.label}>
                <div>
                  <span>{score.label}</span>
                  <b>{score.value}/10</b>
                </div>
                <div className="proof-track">
                  <i style={{ width: `${score.value * 10}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="proof-line">
            Your loop returns the right answer, but it re-scans the whole list on every pass.
          </p>
          <figcaption>A sample review, shown before you write a line.</figcaption>
        </figure>
      </section>

      <section className="steps">
        <h2>Four steps, one loop.</h2>
        <ol className="steps-list">
          {STEPS.map((step) => (
            <li key={step.name}>
              <b>{step.name}</b>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="catalogue" id="catalogue">
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