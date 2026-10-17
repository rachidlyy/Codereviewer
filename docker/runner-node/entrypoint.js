'use strict';
/**
 * Container-side case loop for JavaScript submissions.
 *
 * The JavaScript twin of `docker/runner-python/entrypoint.py`, and the payload
 * it accepts is byte-for-byte the same shape, so `code_runner.py` has one
 * protocol to speak rather than one per language:
 *
 *   stdin:  {"code", "entrypoint", "memory_limit", "budget", "cases": [...]}
 *   stdout: one RESULT_SENTINEL line per case, then one SANDBOX_SENTINEL line
 *
 * Responsibilities, mirroring the Python entrypoint exactly:
 *
 *   1. Run each case in its own child process, so a hard timeout can kill one
 *      case without losing the rest, and so a crash cannot take down the loop.
 *   2. Enforce the whole-submission budget here rather than only on the host,
 *      so the container always ends on its own terms and every case still gets
 *      an honest line.
 *   3. Attribute an out-of-memory kill to a specific case, by reading the
 *      cgroup's monotonic `oom_kill` counter before and after it.
 *   4. Report submission-level memory facts once, at the end.
 *
 * This file is copied into the image at build time. **Editing it does nothing
 * until the image is rebuilt** - see the note in the README.
 */

const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

/**
 * Where the harness lives inside the image.
 *
 * Overridable so this script can be driven directly on a developer machine,
 * where `/opt/runner/harness.js` cannot exist. In the image the default is
 * always used, and nothing in a request can influence it.
 */
const HARNESS_PATH = process.env.CODERUNNER_HARNESS || '/opt/runner/harness.js';

const RESULT_SENTINEL = '__CODERUNNER_RESULT__';

/** Emitted once, after the last case, with submission-level sandbox facts. */
const SANDBOX_SENTINEL = '__CODERUNNER_SANDBOX__';

/** Fallback when a case does not carry its own limit. The API always sends one. */
const DEFAULT_TIMEOUT = 3.0;

/** Fallback whole-submission budget. The API always sends one. */
const DEFAULT_BUDGET = 20.0;

/** Where the per-case child runs. A size-capped tmpfs at run time. */
const WORKDIR = '/work';

/**
 * The working directory for a case's child process.
 *
 * Falls back to the current directory only when `/work` is absent, which
 * happens solely when this script is driven directly on a developer machine.
 * In the image the tmpfs is always mounted at `/work`.
 */
function workdir() {
  return fs.existsSync(WORKDIR) ? WORKDIR : process.cwd();
}

/**
 * Cap on a single child's captured output.
 *
 * The harness caps what it *keeps* at 4000 characters, but the pipe between the
 * two processes is unbounded, so a runaway `console.log` loop would otherwise
 * buffer until the container died. Exceeding this kills the child, which is the
 * right outcome - the harness' own cap means this should be unreachable in
 * practice, so it is a backstop rather than a limit anyone should hit.
 */
const MAX_BUFFER = 4 * 1024 * 1024;

// cgroup v2 accounting. The container is limited with `--memory`, so these
// describe the whole submission rather than one case - but `oom_kill` is a
// monotonic counter, so reading it before and after a case attributes an OOM to
// that case exactly instead of inferring it from a SIGKILL.
const CGROUP_EVENTS = '/sys/fs/cgroup/memory.events';
const CGROUP_PEAK = '/sys/fs/cgroup/memory.peak';
const CGROUP_MAX = '/sys/fs/cgroup/memory.max';

/**
 * Read a single integer out of a cgroup file, or null if unavailable.
 *
 * Returns null rather than throwing: these files are a bonus, not a
 * requirement, and the runner has to work unchanged if a future kernel or
 * runtime does not expose them.
 */
function readCgroupInt(path) {
  let text;
  try {
    text = fs.readFileSync(path, 'utf8').trim();
  } catch (error) {
    return null;
  }
  if (text === 'max') {
    return null; // cgroup's spelling of "no ceiling"
  }
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) ? null : value;
}

/** The container's cumulative OOM-kill count, or 0 when unreadable. */
function oomKills() {
  let text;
  try {
    text = fs.readFileSync(CGROUP_EVENTS, 'utf8');
  } catch (error) {
    return 0;
  }
  for (const line of text.split('\n')) {
    const [key, value] = line.split(' ');
    if (key === 'oom_kill') {
      const parsed = Number.parseInt(value, 10);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
  }
  return 0;
}

/**
 * Submission-level memory facts, read once after the last case.
 *
 * `memory.peak` is a high-water mark for the whole container and cannot be
 * reset without root, so it is reported per submission rather than per case.
 */
function sandboxFacts() {
  return {
    memory_limit_bytes: readCgroupInt(CGROUP_MAX),
    memory_peak_bytes: readCgroupInt(CGROUP_PEAK),
    oom_killed: oomKills() > 0,
  };
}

/**
 * Signal names to numbers, so the API reports a `signal` the same way for every
 * language. Python's `subprocess` hands back a negative return code which it
 * splits into `{exit_code, signal}`; Node hands back a name, which would make
 * the field's type depend on the language.
 */
const SIGNAL_NUMBERS = {
  SIGHUP: 1,
  SIGINT: 2,
  SIGQUIT: 3,
  SIGABRT: 6,
  SIGBUS: 7,
  SIGFPE: 8,
  SIGKILL: 9,
  SIGUSR1: 10,
  SIGSEGV: 11,
  SIGPIPE: 13,
  SIGALRM: 14,
  SIGTERM: 15,
};

/**
 * Split a finished child into an exit code and a signal number.
 *
 * A signalled child has no exit code and a clean one has no signal, so at most
 * one of the two is ever set - the same invariant the Python entrypoint keeps.
 */
function exitFacts(status, signal) {
  if (signal) {
    return { exit_code: null, signal: SIGNAL_NUMBERS[signal] || null };
  }
  if (typeof status === 'number') {
    return { exit_code: status, signal: null };
  }
  return { exit_code: null, signal: null };
}

/**
 * Explain a child that died without producing output.
 *
 * A process killed by the kernel prints nothing at all, so without this the
 * student is told only "the sandbox produced no result" - which is true and
 * useless.
 *
 * `oomKilled` comes from the cgroup's own counter, so the memory case is
 * *known* rather than guessed. A bare SIGKILL is genuinely ambiguous - the
 * cgroup OOM killer and an external `docker kill` look identical from the
 * child's return code - so the two are reported differently on purpose.
 */
function killedMessage(signal, memoryLimit, oomKilled) {
  if (oomKilled) {
    const limit = memoryLimit ? ` of ${memoryLimit}` : '';
    return (
      `Your program ran out of memory - the sandbox ceiling${limit} was reached. ` +
      'Look for a structure that grows without bound, or an input you never stop copying.'
    );
  }
  if (signal === 9) {
    return 'Your program was stopped by the sandbox before it finished.';
  }
  if (signal === 6) {
    return 'Your program aborted. This usually means it ran out of memory or hit an internal error.';
  }
  return `Your program was killed by signal ${signal} before it produced a result.`;
}

/** Extract the sentinel-prefixed JSON line the harness prints. */
function parseHarnessOutput(stdout) {
  const lines = String(stdout || '').split('\n');
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index];
    if (line.startsWith(RESULT_SENTINEL)) {
      try {
        return JSON.parse(line.slice(RESULT_SENTINEL.length));
      } catch (error) {
        return null;
      }
    }
  }
  return null;
}

/** Run one test case in its own child process and return its outcome. */
function runCase(testCase, code, entrypoint, memoryLimit) {
  const index = testCase.index;
  const timeout = Number(testCase.timeout) || DEFAULT_TIMEOUT;
  const payload = JSON.stringify({
    code,
    entrypoint,
    args: testCase.args || [],
  });

  // Snapshot the OOM counter so an out-of-memory kill can be attributed to this
  // case rather than to the submission as a whole.
  const oomBefore = oomKills();
  const started = process.hrtime.bigint();

  let completed;
  try {
    completed = spawnSync(process.execPath, [HARNESS_PATH], {
      input: payload,
      timeout: Math.ceil(timeout * 1000),
      // SIGKILL rather than the SIGTERM default: a student's `process.on`
      // handler cannot exist (they have no `process`), but a slow native
      // operation should still die immediately rather than linger.
      killSignal: 'SIGKILL',
      cwd: workdir(),
      encoding: 'utf8',
      maxBuffer: MAX_BUFFER,
      // An explicit environment rather than inheriting this one, so nothing
      // from the image - `NODE_OPTIONS` above all - can influence the code
      // being tested.
      env: { PATH: process.env.PATH || '' },
    });
  } catch (error) {
    return {
      index,
      ok: false,
      error_type: 'runtime',
      message: `Could not start the interpreter inside the sandbox: ${error.message}`,
      elapsed: Number(process.hrtime.bigint() - started) / 1e9,
      exit_code: null,
      signal: null,
      oom_killed: false,
    };
  }

  const elapsed = Number(process.hrtime.bigint() - started) / 1e9;
  const oomKilled = oomKills() > oomBefore;

  if (completed.error && completed.error.code === 'ETIMEDOUT') {
    return {
      index,
      ok: false,
      error_type: 'timeout',
      message: `Exceeded the ${timeout}s time limit for this test case.`,
      elapsed,
      exit_code: null,
      signal: 9,
      oom_killed: oomKilled,
    };
  }

  const facts = exitFacts(completed.status, completed.signal);
  const reply = parseHarnessOutput(completed.stdout);

  if (reply === null) {
    // A killed child writes nothing, so the signal plus the OOM counter are the
    // only evidence about why.
    let message;
    if (completed.signal) {
      message = killedMessage(SIGNAL_NUMBERS[completed.signal], memoryLimit, oomKilled);
    } else {
      const detail = String(completed.stderr || completed.stdout || 'no output').trim();
      message = `The sandbox produced no result. ${detail.slice(0, 300)}`;
    }
    return {
      index,
      ok: false,
      error_type: 'runtime',
      message,
      elapsed,
      oom_killed: oomKilled,
      ...facts,
    };
  }

  reply.index = index;
  reply.elapsed = elapsed;
  reply.oom_killed = oomKilled;
  return Object.assign(reply, facts);
}

/** Write one result line and flush immediately. */
function emit(result) {
  process.stdout.write(RESULT_SENTINEL + JSON.stringify(result) + '\n');
}

function main() {
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch (error) {
    emit({
      ok: false,
      error_type: 'runtime',
      message: `The sandbox could not read its request: ${error.message}`,
    });
    return;
  }

  const code = payload.code || '';
  const entrypoint = payload.entrypoint || '';
  const cases = payload.cases || [];
  // Passed in rather than read from the environment so the message can name the
  // actual ceiling, and so it stays correct if the limit is changed.
  const memoryLimit = payload.memory_limit;
  const budget = Number(payload.budget) || DEFAULT_BUDGET;

  if (!cases.length) {
    emit({
      ok: false,
      error_type: 'runtime',
      message: 'The sandbox received no test cases.',
    });
    return;
  }

  // The whole-submission budget is enforced here as well as on the host. The
  // host's backstop kills the container, which loses any case that had not
  // started yet; enforcing it in here means the container always ends on its
  // own terms and every case still gets an honest line.
  const deadline = performance.now() + budget * 1000;

  for (const testCase of cases) {
    if (performance.now() > deadline) {
      emit({
        index: testCase.index,
        ok: false,
        error_type: 'timeout',
        message: 'Submission exceeded the total time budget.',
        elapsed: 0.0,
        exit_code: null,
        signal: null,
        oom_killed: false,
      });
      continue;
    }
    // One bad case must not abort the rest: every case gets a line.
    try {
      emit(runCase(testCase, code, entrypoint, memoryLimit));
    } catch (error) {
      emit({
        index: testCase.index,
        ok: false,
        error_type: 'runtime',
        message: `${error.name}: ${error.message}`,
        exit_code: null,
        signal: null,
        oom_killed: false,
      });
    }
  }

  // One final line with submission-level sandbox facts. Sent after the cases so
  // that a container killed mid-run still yields everything above it.
  process.stdout.write(SANDBOX_SENTINEL + JSON.stringify(sandboxFacts()) + '\n');
}

main();
