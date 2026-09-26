// The tmux allowlist.
//
// These assertions run against assertAllowedArgv/buildArgv rather than against a
// live tmux, on purpose: the allowlist IS the security property, and it has to be
// assertable on a host where tmux is not installed at all. A suite that could only
// check this by running tmux would skip itself on Windows and on any CI box
// without it - which is exactly where a regression would go unnoticed.
//
// Nothing here spawns a process. If any of it ever does, the refusal has stopped
// happening before execFile, and that is itself the bug.

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  ALLOWED_VERBS,
  TMUX_SOCKET,
  TMUX_TIMEOUT_MS,
  TmuxRefusal,
  assertAllowedArgv,
  buildArgv,
  tmux,
} from "../src/tmux.ts";

/** The four the brief names explicitly. Each must be refused, with a reason. */
const FORBIDDEN = ["send-keys", "new-session", "kill-session", "respawn-pane"];

/**
 * Everything else that can reach a shell or a pane's input. Not a denylist - the
 * implementation is allowlist-only - but the cases worth naming in a test, because
 * a future "just add this one verb" is what this suite exists to stop.
 */
const ALSO_FORBIDDEN = [
  "run-shell",
  "if-shell",
  "split-window",
  "new-window",
  "kill-pane",
  "kill-server",
  "pipe-pane",
  "load-buffer",
  "paste-buffer",
  "save-buffer",
  "source-file",
  "command-prompt",
  "confirm-before",
  "bind-key",
  "server-access",
];

describe("the tmux allowlist", () => {
  test("each explicitly forbidden verb is refused, and says why", () => {
    for (const verb of FORBIDDEN) {
      let caught: unknown;
      try {
        assertAllowedArgv([verb, "-t", "agent-1", "echo hi"]);
      } catch (error: unknown) {
        caught = error;
      }
      assert.ok(caught instanceof TmuxRefusal, `${verb} was NOT refused`);
      assert.equal(caught.verb, verb);
      assert.match(
        caught.message,
        /display geometry and nothing else/,
        `${verb}: the refusal must state the rule`,
      );
      assert.ok(
        caught.message.length > `tmux ${verb} refused: .`.length + 20,
        `${verb}: the refusal must carry a reason, not just a denial`,
      );
    }
  });

  test("send-keys names the actual consequence, not just 'not allowed'", () => {
    const error = refusalFrom(() => assertAllowedArgv(["send-keys", "-t", "%1", "rm -rf /", "Enter"]));
    assert.match(error.message, /arbitrary code execution/);
  });

  test("every other route to a shell or a pane's input is refused by default", () => {
    for (const verb of ALSO_FORBIDDEN) {
      assert.throws(
        () => assertAllowedArgv([verb]),
        TmuxRefusal,
        `${verb} reached tmux - the allowlist is not default-deny`,
      );
    }
  });

  test("a verb nobody has thought of yet is refused", () => {
    // The point of an allowlist: this needs no maintenance to keep working.
    assert.throws(() => assertAllowedArgv(["some-future-tmux-command"]), TmuxRefusal);
    assert.throws(() => assertAllowedArgv(["SEND-KEYS"]), TmuxRefusal, "casing is not a bypass");
    assert.throws(() => assertAllowedArgv([" send-keys"]), TmuxRefusal, "padding is not a bypass");
  });

  test("an empty argv is refused rather than defaulting to something", () => {
    const error = refusalFrom(() => assertAllowedArgv([]));
    assert.match(error.message, /no command given/);
  });

  test("a NUL byte in any argument is refused", () => {
    // execFile rejects these itself, but with an error that names neither tmux nor
    // the argument. Refuse it here so the message says what happened.
    assert.throws(() => assertAllowedArgv(["list-panes", "-F", "#{pane_id}\u0000"]), TmuxRefusal);
  });

  test("the six display-geometry verbs ARE permitted", () => {
    const expected = [
      "list-sessions",
      "list-panes",
      "capture-pane",
      "display-message",
      "set-option",
      "resize-window",
    ];
    assert.deepEqual([...ALLOWED_VERBS].sort(), [...expected].sort());
    for (const verb of expected) {
      assert.doesNotThrow(() => assertAllowedArgv([verb]), `${verb} should be permitted`);
    }
  });

  test("the allowlist and the explained refusals cannot overlap", () => {
    // The reason this exists: a differential check widened ALLOWED_VERBS to
    // include send-keys, and no allowlist test went red - EXPLAINED_REFUSALS is
    // consulted first, so the call was still refused, by the list of error
    // messages rather than by the security boundary. Now the module refuses to
    // load in that state, which turns the whole file red at once.
    const overlap = FORBIDDEN.filter((verb) => ALLOWED_VERBS.has(verb));
    assert.deepEqual(overlap, [], "a verb is permitted or it is refused, never both");
  });

  test("a permitted verb's own arguments are not re-screened as verbs", () => {
    // `capture-pane -t send-keys` is a pane named send-keys, not a send-keys call.
    // Screening every argument against the verb list would break legitimate calls
    // while stopping nothing.
    assert.doesNotThrow(() => assertAllowedArgv(["capture-pane", "-t", "send-keys", "-p"]));
  });
});

describe("the argv is an argv", () => {
  test("buildArgv puts the socket in front, as separate arguments", () => {
    assert.deepEqual(buildArgv(["list-panes", "-a"]), ["-L", TMUX_SOCKET, "list-panes", "-a"]);
  });

  test("shell metacharacters survive as data because there is no shell", () => {
    // If anything ever joined these into a command line, this pane name would be a
    // command substitution. As an argv element it is just a name that will not
    // match any pane.
    const hostile = "$(touch /tmp/pwned); rm -rf ~ & echo `id`";
    const argv = buildArgv(["capture-pane", "-t", hostile]);
    assert.equal(argv[4], hostile, "the argument must pass through byte for byte");
    assert.equal(argv.length, 5, "and must not have been split on anything");
  });

  test("buildArgv refuses before it builds", () => {
    assert.throws(() => buildArgv(["send-keys", "-t", "%1", "whoami"]), TmuxRefusal);
  });

  test("the timeout is bounded", () => {
    assert.equal(TMUX_TIMEOUT_MS, 5000);
  });
});

describe("tmux() delivers a refusal as a rejection", () => {
  // A function typed Promise<T> that throws synchronously escapes .catch() and
  // takes the process down. Refusals must arrive the same way every other failure
  // does.
  for (const verb of FORBIDDEN) {
    test(`${verb} rejects, without spawning`, async () => {
      await assert.rejects(() => tmux([verb, "-t", "%1"]), TmuxRefusal);
    });
  }
});

function refusalFrom(action: () => unknown): TmuxRefusal {
  try {
    action();
  } catch (error: unknown) {
    assert.ok(error instanceof TmuxRefusal, `expected a TmuxRefusal, got: ${String(error)}`);
    return error;
  }
  assert.fail("expected a TmuxRefusal, but nothing was thrown");
}
