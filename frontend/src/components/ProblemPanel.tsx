import { Lightbulb } from 'lucide-react';

import type { ProblemSummary } from '../types';

type Props = {
  problem: ProblemSummary;
};

export default function ProblemPanel({ problem }: Props) {
  return (
    <aside className="problem-panel">
      <h4>Problem</h4>
      <p>{problem.description}</p>

      <h4>Examples</h4>
      {problem.examples.map((example, index) => (
        <div className="example" key={index}>
          <div>
            <span>Input</span>
            <code>{example.input}</code>
          </div>
          <div>
            <span>Output</span>
            <code>{example.output}</code>
          </div>
        </div>
      ))}

      <div className="hint-box">
        <Lightbulb size={17} />
        <div>
          <b>Need a hint?</b>
          <p>Try the problem yourself first. AI review can help after you run your code.</p>
        </div>
      </div>
    </aside>
  );
}
