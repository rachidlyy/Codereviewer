import { CheckCircle2, CircleAlert, Clock, Terminal } from 'lucide-react';

import type { RunResult, SandboxInfo, TestCaseResult } from '../types';

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

/** How many differing positions to spell out before summarising the rest. */
const MAX_DIFF_ROWS = 6;

/**
 * Render a duration at a readable scale.
 *
 * `compute` for a small case is genuinely microseconds, and printing that as
 * "0.00 s" would make every fast case look identical — which is the whole
 * reason `compute` exists as a separate field.
 */
function formatSeconds(value: number): string {
  if (!value) return '0 ms';
  if (value < 0.001) return `${Math.round(value * 1_000_000)} µs`;
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  return `${value.toFixed(2)} s`;
}

function formatBytes(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const mb = value / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
  return `${Math.round(value / 1024)} KB`;
}

/** A JSON value on one line, for the diff table. */
function formatValue(value: unknown): string {
  if (typeof value === 'string') return JSON.stringify(value);
  const text = JSON.stringify(value);
  return text === undefined ? String(value) : text;
}

function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

type Mismatch = { index: number; expected: unknown; actual: unknown };

/**
 * Compare two arrays position by position and return only the differences.
 *
 * The point of doing this here rather than showing two reprs side by side is
 * that `[0, 1]` and `[1, 0]` are the same length and the same values, so as
 * text they look nearly identical. Naming the index that differs is the
 * difference between a student spotting the bug and re-reading the same line
 * five times.
 */
function arrayMismatches(expected: unknown[], actual: unknown[]): Mismatch[] {
  const rows: Mismatch[] = [];
  const length = Math.max(expected.length, actual.length);
  for (let i = 0; i < length; i += 1) {
    const expectedItem = expected[i];
    const actualItem = actual[i];
    if (JSON.stringify(expectedItem) === JSON.stringify(actualItem)) continue;
    rows.push({ index: i, expected: expectedItem, actual: actualItem });
  }
  return rows;
}

function ArrayDiff({ expected, actual }: { expected: unknown[]; actual: unknown[] }) {
  const mismatches = arrayMismatches(expected, actual);
  const shown = mismatches.slice(0, MAX_DIFF_ROWS);
  const lengthNote =
    expected.length === actual.length
      ? null
      : `you returned ${actual.length}, ${expected.length} expected`;

  return (
    <div className="diff">
      <p className="diff-head">
        {mismatches.length === 0
          ? 'Same values, different order'
          : `${mismatches.length} of ${Math.max(expected.length, actual.length)} positions differ`}
        {lengthNote ? ` · ${lengthNote}` : null}
      </p>
      <ol className="diff-rows">
        {shown.map((row) => (
          <li key={row.index}>
            <span className="diff-index">[{row.index}]</span>
            <span className="diff-expected">expected {formatValue(row.expected)}</span>
            <span className="diff-arrow">got</span>
            <span className="diff-actual">{formatValue(row.actual)}</span>
          </li>
        ))}
      </ol>
      {mismatches.length > shown.length ? (
        <p className="diff-more">
          and {mismatches.length - shown.length} more position
          {mismatches.length - shown.length === 1 ? '' : 's'}
        </p>
      ) : null}
    </div>
  );
}

/** The sandbox's own numbers, shown when they explain a failure. */
function SandboxNote({ sandbox }: { sandbox: SandboxInfo }) {
  const peak = formatBytes(sandbox.memory_peak_bytes);
  const limit = formatBytes(sandbox.memory_limit_bytes);

  if (!sandbox.oom_killed) return null;

  return (
    <div className="sandbox-note">
      <p className="sandbox-line">
        <b>Out of memory.</b> The sandbox stopped your program after it reached{' '}
        {limit ?? 'the memory ceiling'}
        {peak ? ` (it peaked at ${peak})` : ''}.
      </p>
      <p className="sandbox-meta">
        {limit ? <>memory limit {limit}</> : null}
        {limit && peak ? ' · ' : null}
        {peak ? <>peak used {peak}</> : null}
      </p>
    </div>
  );
}

/** Everything worth showing about one case, inside its expandable row. */
function CaseDetail({ test, sandbox }: { test: TestCaseResult; sandbox: SandboxInfo | null }) {
  const expected = test.expected_value;
  const actual = test.actual_value;
  const diffable = isArray(expected) && isArray(actual);
  const killed = test.signal !== null && test.signal !== undefined;
  const showMemory = test.oom_killed === true && sandbox !== null;

  return (
    <div className="case-detail">
      {test.message ? <p className="case-message">{test.message}</p> : null}

      {diffable ? (
        <ArrayDiff expected={expected} actual={actual} />
      ) : (
        <p className="case-values">
          <span>
            expected <b>{test.expected ?? '—'}</b>
          </span>
          {test.actual !== null ? (
            <span>
              got <b className="mismatch">{test.actual}</b>
            </span>
          ) : null}
        </p>
      )}

      {test.stdout ? (
        <div className="case-output">
          <p className="output-label">
            <Terminal size={12} /> Your output
            {test.stdout_truncated ? <em> · truncated</em> : null}
          </p>
          <pre>{test.stdout}</pre>
          {test.stdout_truncated ? (
            <p className="output-note">
              Output was cut off to keep the response small. If you are printing in a loop,
              print less — or use the debugger of your choice and remove the prints.
            </p>
          ) : null}
        </div>
      ) : null}

      {showMemory && sandbox ? <SandboxNote sandbox={sandbox} /> : null}

      {killed && !showMemory ? (
        <p className="case-exit">Stopped by signal {test.signal}.</p>
      ) : null}

      {test.exit_code !== null && test.exit_code !== undefined && test.exit_code !== 0 ? (
        <p className="case-exit">Exited with code {test.exit_code}.</p>
      ) : null}
    </div>
  );
}

/** True when a case has something to reveal beyond its one-line summary. */
function hasDetail(test: TestCaseResult): boolean {
  return Boolean(
    test.stdout ||
      test.message ||
      test.oom_killed ||
      (test.signal !== null && test.signal !== undefined) ||
      (isArray(test.expected_value) && isArray(test.actual_value)),
  );
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

  const totalCompute = result.tests.reduce((sum, test) => sum + (test.compute || 0), 0);

  return (
    <div className="results">
      <div className="result-head">
        <h3>
          {result.passed}/{result.total} tests passed
        </h3>
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

      {/* Only when the sandbox is the reason something failed. On a passing
          run the memory ceiling is trivia, and on a non-memory failure it is
          not the explanation. */}
      {result.sandbox?.oom_killed ? <SandboxNote sandbox={result.sandbox} /> : null}

      <div className="tests">
        {result.tests.map((test) =>
          hasDetail(test) ? (
            <details className={test.passed ? 'test pass' : 'test fail'} key={test.index}>
              <summary>
                {test.passed ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
                <b>Test {test.index}</b>
                <span className="test-name">{test.name}</span>
                <span className="case-time">{formatSeconds(test.compute)}</span>
              </summary>
              <CaseDetail test={test} sandbox={result.sandbox} />
            </details>
          ) : (
            <div className={test.passed ? 'test pass' : 'test fail'} key={test.index}>
              {test.passed ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
              <b>Test {test.index}</b>
              <span className="test-name">{test.name}</span>
              <span className="case-time">{formatSeconds(test.compute)}</span>
            </div>
          ),
        )}
        <div className="exec">
          <Clock size={14} /> Your code ran in <b>{formatSeconds(totalCompute)}</b>
          <span className="exec-total">· {result.execution_time}s total including startup</span>
        </div>
      </div>

      {stale && (
        <p className="stale-note">
          Your code changed since this run. Run again to test the current version.
        </p>
      )}
    </div>
  );
}
