import { ChevronRight } from 'lucide-react';

import type { ProblemSummary } from '../types';

type Props = {
  problem: ProblemSummary;
  onSelect: (problem: ProblemSummary) => void;
};

export default function ProblemCard({ problem, onSelect }: Props) {
  return (
    <button className="problem-card" onClick={() => onSelect(problem)}>
      <div className="card-top">
        <span className={'difficulty ' + problem.difficulty.toLowerCase()}>
          {problem.difficulty}
        </span>
        <span className="arrow">
          <ChevronRight size={18} />
        </span>
      </div>
      <h3>{problem.title}</h3>
      <p>{problem.description}</p>
      <div className="tags">
        {problem.tags.map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
      </div>
    </button>
  );
}
