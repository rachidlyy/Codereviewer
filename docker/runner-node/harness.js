'use strict';
/**
 * Child-process harness that executes one test case against student code.
 *
 * The JavaScript twin of `backend/app/services/_runner_harness.py`, and it
 * speaks the same protocol so `code_runner.py` needs no language-specific
 * parsing:
 *
 *   stdin:  {"code": str, "entrypoint": str, "args": [<json values>]}
 *   stdout: a single line beginning with RESULT_SENTINEL followed by JSON
 *
 * This file is **never imported** by the API. `entrypoint.js` launches it as a
 * separate `node` process, one per test case, so that:
 *
 *   - a slow or infinite loop in student code can be killed by the parent via a
 *     hard timeout;
 *   - a crash in student code cannot take down the case loop;
 *   - student code cannot see the sandbox's environment.
 *
 * Like the Python harness, **this harness does not compare anything**.
 * `expected` is never sent to it: the comparison rules live in exactly one
 * place (`code_runner.py`) instead of once per language, and student code
 * cannot read the answer out of its own process.
 *
 * `compute` is seconds spent inside the student's own code, measured from
 * executing their module to getting the answer. It deliberately excludes Node
 * startup (~40ms), which is roughly a thousand times what a typical solution
 * does - including it would make the reported time meaningless and would defeat
 * the input-scaling measurements the complexity analysis depends on.
 */

const fs = require('node:fs');
const vm = require('node:vm');
const util = require('node:util');

const RESULT_SENTINEL = '__CODERUNNER_RESULT__';

// Keep captured student output bounded so a runaway console.log loop cannot
// exhaust memory or bloat the API response. Must stay equal to
// MAX_CAPTURED_CHARS in the Python harness - `check_runner.py` section 11
// asserts the two agree, because the UI's truncation copy depends on it.
const MAX_CAPTURED_CHARS = 4000;

// The same bound applies to a returned value's repr. A student can return a
// million-element array; the response must not grow to match.
const MAX_REPR_CHARS = 2000;

//: How deep `util.inspect` walks a returned value before printing [Object].
//: Only affects the repr fallback - JSON-carried values are unaffected.
const REPR_DEPTH = 4;

//: How deep `isJsonSafe` walks before giving up and using the repr. Also the
//: cycle guard: a cyclic value would otherwise recurse forever.
const MAX_JSON_DEPTH = 8;

const TRUNCATION_MARKER = ' ... (truncated)';

function truncate(text, limit) {
  if (text.length <= limit) {
    return text;
  }
  return text.slice(0, limit) + TRUNCATION_MARKER;
}

function failure(errorType, message, extra) {
  return Object.assign({ ok: false, error_type: errorType, message: message }, extra || {});
}

/**
 * A stdout replacement that stops storing once it is full.
 *
 * Accumulating everything would let a runaway `console.log` loop exhaust the
 * container's memory ceiling, and the run would be reported as an out-of-memory
 * failure. That verdict is technically true and completely useless: the
 * student's actual mistake was printing too much, and the report should say so.
 *
 * `truncated` is set only when a write was actually cut short, not merely when
 * the buffer happens to be full - otherwise output that lands exactly on the
 * limit would be labelled truncated although nothing was lost.
 */
class CappedBuffer {
  constructor(limit) {
    this.limit = limit;
    this.chunks = [];
    this.size = 0;
    this.truncated = false;
  }

  write(text) {
    const value = String(text);
    if (this.size < this.limit) {
      const room = this.limit - this.size;
      if (value.length > room) {
        this.truncated = true;
      }
      this.chunks.push(value.slice(0, room));
      this.size += Math.min(value.length, room);
    } else if (value.length > 0) {
      this.truncated = true;
    }
    // Report the full length, as a real stream would: `console.log` and
    // `process.stdout.write` callers rely on the return value.
    return value.length;
  }

  value() {
    const text = this.chunks.join('');
    return this.truncated ? text + TRUNCATION_MARKER : text;
  }
}

/**
 * Whether JSON can carry this value *faithfully*.
 *
 * `JSON.stringify` is not the test on its own, because it silently succeeds on
 * values it mangles: a `Map` or `Set` stringifies to `{}` (its entries are not
 * own enumerable properties), `NaN` and `Infinity` become `null`, and a `Date`
 * becomes a string. A student returning `new Map([['a', 1]])` would then be told
 * their answer was `{}` - a wrong answer reported confidently.
 *
 * Python's harness gets this for free: `json.dumps` raises on a `set` and the
 * repr fallback takes over. This is the equivalent guard.
 *
 * `Object.prototype.toString` rather than a prototype comparison because the
 * value was built inside the vm context and therefore has that realm's
 * `Object.prototype`, not this one's - a `proto === Object.prototype` check
 * would reject every plain object a student returns.
 *
 * Depth-limited because the value may be cyclic, which JSON also cannot carry.
 */
function isJsonSafe(value, depth) {
  if (depth > MAX_JSON_DEPTH) {
    return false;
  }
  if (value === null) {
    return true;
  }

  const type = typeof value;
  if (type === 'boolean' || type === 'string') {
    return true;
  }
  if (type === 'number') {
    // NaN and the infinities are `typeof number` but JSON writes them as null.
    return Number.isFinite(value);
  }

  const tag = Object.prototype.toString.call(value);
  if (tag === '[object Array]') {
    return Array.prototype.every.call(value, (item) => isJsonSafe(item, depth + 1));
  }
  if (tag === '[object Object]') {
    return Object.keys(value).every((key) => isJsonSafe(value[key], depth + 1));
  }
  return false;
}

/**
 * Round-trip a value through JSON, or return undefined when it cannot survive.
 *
 * Round-tripping rather than only stringifying because this is what
 * `code_runner.py` will actually receive - a value that cannot make the trip is
 * caught here instead of silently arriving as something else.
 */
function tryJson(value) {
  if (!isJsonSafe(value, 0)) {
    return undefined;
  }
  let text;
  try {
    text = JSON.stringify(value);
  } catch (error) {
    return undefined;
  }
  if (text === undefined) {
    return undefined;
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    return undefined;
  }
}

function success(actual, computeSeconds) {
  const encoded = tryJson(actual);
  const repr = truncate(
    util.inspect(actual, { depth: REPR_DEPTH, maxArrayLength: 100, breakLength: Infinity }),
    MAX_REPR_CHARS,
  );

  if (encoded === undefined) {
    // A value JSON cannot carry - a Map, a Set, a class instance, undefined.
    // `code_runner.py` compares the reprs as text in that case, which is the
    // best available evidence.
    return { ok: true, serialisable: false, actual_repr: repr, compute: computeSeconds };
  }

  return {
    ok: true,
    serialisable: true,
    actual: encoded,
    actual_repr: repr,
    compute: computeSeconds,
  };
}

/**
 * A student-facing name for the entrypoint, safe to embed in generated source.
 *
 * The name comes from our own `problems.json`, never from a request, so this is
 * defence in depth rather than a live injection path - but a name that is not a
 * plain identifier would silently produce a confusing `ReferenceError`, so it
 * is rejected explicitly.
 */
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

/**
 * Pull a line number out of a `vm.Script` syntax error, clamped to the
 * student's own code.
 *
 * Node formats these as `main.js:3` on the first stack line, with the offending
 * source line beneath it. The clamp is load-bearing: the compiled source is the
 * student's code *plus* the appended lookup expression, so an error at the end
 * of their code - an unclosed brace, most commonly - is reported against the
 * appended line. Measured: a three-line function with a missing `}` reported
 * "line 5", pointing the student at a line that does not exist in their editor.
 */
function syntaxLine(error, code) {
  const text = String((error && error.stack) || '');
  const match = text.match(/main\.js:(\d+)/);
  if (!match) {
    return null;
  }
  // Trailing blank lines are not something a student can point at, so the
  // clamp is against the last line that actually has content.
  const studentLines = code.replace(/\n+$/, '').split('\n').length;
  return Math.max(1, Math.min(Number(match[1]), studentLines));
}

function evaluate(code, entrypoint, args) {
  if (!IDENTIFIER.test(entrypoint)) {
    return failure('runtime', `The problem's entrypoint name (${JSON.stringify(entrypoint)}) is not a valid function name.`);
  }

  // The entrypoint is looked up by appending its bare name as the script's last
  // expression, rather than reading it off the context object. This matters:
  // a top-level `function f(){}` becomes a property of the context, but
  // `const f = () => {}` does not - it lives in the script's lexical scope. By
  // evaluating the name *in the same script* both forms resolve, which is what
  // Python's `namespace.get(entrypoint)` achieves for the other language.
  //
  // `typeof` guards the lookup so a missing entrypoint yields undefined instead
  // of a ReferenceError, which lets the message below name the real problem.
  const source = `${code}\n;\ntypeof ${entrypoint} !== 'undefined' ? ${entrypoint} : undefined;`;

  let script;
  try {
    script = new vm.Script(source, { filename: 'main.js' });
  } catch (error) {
    if (error instanceof SyntaxError) {
      const line = syntaxLine(error, code);
      return failure('syntax', `Syntax error on line ${line || 1}: ${error.message}`, { line: line || 1 });
    }
    return failure('syntax', `Your code could not be parsed: ${error.message}`);
  }

  // A fresh context per case: intrinsics (Math, JSON, Array...) come with it,
  // and nothing from this process leaks in. `require`, `process` and `module`
  // are deliberately absent - student code has no business with them, and the
  // container is the real security boundary rather than this context.
  const context = vm.createContext({ console: studentConsole });

  // Time the student's own code, from executing their module to getting the
  // answer. Node startup is excluded, so this measures the algorithm.
  const started = process.hrtime.bigint();

  let candidate;
  try {
    candidate = script.runInContext(context);
  } catch (error) {
    return failure('runtime', `${error.name}: ${error.message}`);
  }

  if (candidate === undefined) {
    return failure(
      'runtime',
      `Your code does not define anything called '${entrypoint}'. Keep the function name from the starter code.`,
    );
  }
  if (typeof candidate !== 'function') {
    return failure('runtime', `'${entrypoint}' is defined but is not a function.`);
  }

  let actual;
  try {
    actual = candidate.apply(undefined, args);
  } catch (error) {
    return failure('runtime', `${error.name}: ${error.message}`);
  }

  return success(actual, Number(process.hrtime.bigint() - started) / 1e9);
}

/**
 * `console` as student code sees it: every method funnels into the capture
 * buffer, so nothing student code prints can corrupt the result line.
 *
 * Defined before the buffer exists because `evaluate` builds the context; the
 * buffer is installed by `main` via `setTarget`.
 */
let captureTarget = null;

function emitToCapture(parts) {
  if (captureTarget === null) {
    return;
  }
  captureTarget.write(parts.map((part) => (typeof part === 'string' ? part : util.inspect(part))).join(' ') + '\n');
}

const studentConsole = {
  log: (...parts) => emitToCapture(parts),
  info: (...parts) => emitToCapture(parts),
  warn: (...parts) => emitToCapture(parts),
  error: (...parts) => emitToCapture(parts),
  debug: (...parts) => emitToCapture(parts),
};

function readStdin() {
  // readFileSync(0) rather than a readSync loop: it reads to EOF in one call and
  // cannot raise EAGAIN on a non-blocking pipe, which a manual loop can.
  return fs.readFileSync(0, 'utf8');
}

function main() {
  const realStdoutWrite = process.stdout.write.bind(process.stdout);
  let payload;
  try {
    payload = JSON.parse(readStdin());
  } catch (error) {
    realStdoutWrite(
      RESULT_SENTINEL + JSON.stringify(failure('runtime', `Runner could not read the request: ${error.message}`)) + '\n',
    );
    return;
  }

  const captured = new CappedBuffer(MAX_CAPTURED_CHARS);
  captureTarget = captured;

  const result = evaluate(payload.code || '', payload.entrypoint || '', payload.args || []);

  const output = captured.value();
  if (output) {
    result.stdout = output;
    // Reported separately from the marker inside the text so the UI can explain
    // *why* the output stops, rather than just showing an ellipsis.
    result.stdout_truncated = captured.truncated;
  }

  realStdoutWrite(RESULT_SENTINEL + JSON.stringify(result) + '\n');
}

main();
