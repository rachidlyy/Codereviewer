import { CheckCircle2, CircleAlert, Terminal } from 'lucide-react';

import type { RunResult } from '../types';

type Props = {
  result: RunResult | null;
  /** True when the editor content changed after the last run. */
  stale: boolean;
};

const STATUS_LABEL: Record<RunResult['status'], string> = {
  passed: 'passed',
  partial: 'partial',
  failed: 'failed',
  error: 'error',
  timeout: 'timeout',
};

/**
 * `actual`/`expected` are now real JSON values (numbers, strings, booleans,
 * arrays) rather than the pre-stringified text the backend used to send.
 * This turns whatever came back into readable text - e.g. the array
 * `[0, 1]` becomes the string "[0,1]" instead of React silently rendering
 * an array as "0,1" via implicit toString().
 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

export default function TestResults({ result, stale }: Props) {
  if (!result) {
    return (
      <div className="results">
        <div className="empty-result">
          <Terminal size={20} />
          <div>
            <b>Run your code to see test results</b>
            <p>Test results will appear here after execution.</p>
          </div>
        </div>
      </div>
    );
  }

  const failures = result.tests.filter(
    (test) => !test.passed && (test.actual != null || test.expected != null),
  );

  return (
    <div className="results">
      <div className="result-head">
        <div>
          <span className="eyebrow">TEST RESULTS</span>
          <h3>
            {result.passed}/{result.total} tests passed
          </h3>
        </div>
        <span className={'status ' + STATUS_LABEL[result.status]}>{STATUS_LABEL[result.status]}</span>
      </div>

      {result.error && (
        <div className="error">
          <CircleAlert size={17} />
          <div>
            <b>{result.error.title}</b>
            <p>{result.error.message}</p>
            {result.error.line ? <p className="error-line">Check line {result.error.line}.</p> : null}
            {result.error.type === 'timeout' && result.error.detail ? (
              <p className="error-line">{result.error.detail}</p>
            ) : null}
          </div>
        </div>
      )}

      <div className="tests">
        {result.tests.map((test) => (
          <div
            className={test.passed ? 'test pass' : 'test fail'}
            key={test.index}
            title={test.message ?? ''}
          >
            {test.passed ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
            <b>Test {test.index}</b>
            <span className="test-name">{test.name}</span>
          </div>
        ))}
        <div className="exec">
          <Terminal size={14} /> Execution time <b>{result.execution_time}s</b>
        </div>
      </div>

      {failures.length > 0 && (
        <div className="failure-detail">
          {failures.map((test) => (
            <div className="failure-row" key={test.index}>
              <span className="failure-label">{test.name}</span>
              <code>
                expected <b>{formatValue(test.expected)}</b>
                {test.actual != null ? (
                  <>
                    {' '}
                    · got <b className="mismatch">{formatValue(test.actual)}</b>
                  </>
                ) : null}
              </code>
            </div>
          ))}
        </div>
      )}

      {stale && (
        <p className="stale-note">
          Your code changed since this run. Run again to test the current version.
        </p>
      )}
    </div>
  );
}
