// THE RULE, and it is the whole point of this file:
//
//     THE API WRITES TMUX DISPLAY GEOMETRY AND NOTHING ELSE.
//
// Not keystrokes, not lifecycle. The panes belong to the operator and to the
// agents running in them. This process may ask tmux what is on screen and it may
// change how that is laid out; it may not type into a pane, create one, kill one,
// or restart a process inside one.
//
// WHY THAT LINE AND NOT A LOOSER ONE. SPEC_CC.md's standing constraints already
// say "Terminals stay read-only; the page never sends keystrokes to an agent."
// The panes hold live coding agents with credentials and write access to real
// repositories. `tmux send-keys` into one is arbitrary code execution wearing the
// operator's identity, and it is indistinguishable in the log from the operator
// doing it themselves. Geometry - what is visible, how big - is the largest thing
// that can be granted without granting that.
//
// WHY AN ALLOWLIST AND NOT A DENYLIST. A denylist is a list of the attacks
// someone thought of. tmux has upwards of a hundred commands and gains more; the
// next one that can write to a pane will not be on a denylist written today.
// run-shell, if-shell, split-window, pipe-pane, load-buffer, paste-buffer, source-
// file and command-prompt are each a route to execution, and that is only the ones
// worth naming. So the permitted verbs are enumerated and everything else, known
// or not, is refused by default.
//
// WHY argv AND shell:false. execFile with an array never constructs a command
// line, so a pane name containing `;` or `$(...)` is an argument, not syntax.
// There is no shell in the picture to re-parse it. The same class of bug that
// scripts/wsl.py exists for - a string being parsed by a shell nobody meant to
// involve - simply cannot occur here.

import { execFile } from "node:child_process";

/** The tmux socket this repo uses everywhere. agentmux.sh, run_tests.sh, all of it. */
export const TMUX_SOCKET = "agentmux";

/** How long a tmux call may take before it is killed. */
export const TMUX_TIMEOUT_MS = 5000;

/** Bounded output: a capture-pane of a long scrollback should not become a heap problem. */
export const TMUX_MAX_BUFFER = 1024 * 1024;

/**
 * Display geometry, and only display geometry.
 *
 *   list-sessions     what exists
 *   list-panes        what exists, per session
 *   capture-pane      what is on screen (read)
 *   display-message   ask tmux to resolve a format string (read)
 *   set-option        pane/window display options
 *   resize-window     the geometry write this API exists to make
 */
export const ALLOWED_VERBS: ReadonlySet<string> = new Set([
  "list-sessions",
  "list-panes",
  "capture-pane",
  "display-message",
  "set-option",
  "resize-window",
]);

/**
 * Verbs named explicitly so their refusal says WHY rather than "not allowed".
 *
 * These four are the ones a future handler is most likely to reach for in good
 * faith - "just restart the pane", "just send a newline" - and the ones that most
 * need the answer to be no with a reason attached.
 */
const EXPLAINED_REFUSALS: ReadonlyMap<string, string> = new Map([
  ["send-keys", "sending keystrokes to an agent pane is arbitrary code execution as the operator"],
  ["new-session", "pane lifecycle belongs to agentmux.sh, not to the API"],
  ["kill-session", "pane lifecycle belongs to agentmux.sh, not to the API"],
  ["respawn-pane", "restarting a pane's process discards the agent running in it"],
]);

// THE INVARIANT: the two lists must be disjoint, and saying so at module load is
// the point.
//
// Found by a differential check on 2026-09-25. Adding "send-keys" to
// ALLOWED_VERBS did not turn a single allowlist test red, because
// EXPLAINED_REFUSALS is consulted first and refused it anyway. The guard held, but
// for the wrong reason - the allowlist, which is the actual security boundary, had
// been widened to include arbitrary code execution and the only thing standing
// there was a list of error messages.
//
// A verb in both lists is a contradiction. Resolving it quietly in favour of
// refusal is what made the widening invisible, so it is resolved loudly instead:
// the module fails to load, and every route that imports it fails with it.
const CONTRADICTORY = [...EXPLAINED_REFUSALS.keys()].filter((verb) => ALLOWED_VERBS.has(verb));
if (CONTRADICTORY.length > 0) {
  throw new Error(
    `src/tmux.ts is self-contradictory: ${CONTRADICTORY.join(", ")} appears in both ` +
      "ALLOWED_VERBS and EXPLAINED_REFUSALS. A verb is permitted or it is refused. " +
      "If this fired because a verb was just added to the allowlist, read what it " +
      "does to a pane before deciding that was intended.",
  );
}

export class TmuxRefusal extends Error {
  readonly verb: string;

  constructor(verb: string, reason: string) {
    super(
      `tmux ${verb === "" ? "<empty>" : verb} refused: ${reason}. ` +
        "The API writes tmux display geometry and nothing else. Permitted verbs: " +
        [...ALLOWED_VERBS].join(", ") + ".",
    );
    this.name = "TmuxRefusal";
    this.verb = verb;
  }
}

/**
 * Screen one argv. Exported so it can be tested without a tmux on the machine -
 * the allowlist is the security property, and it must be assertable on a host
 * where tmux does not exist at all.
 */
export function assertAllowedArgv(args: readonly string[]): void {
  const verb = args[0];
  if (verb === undefined) {
    throw new TmuxRefusal("", "no command given");
  }
  for (const arg of args) {
    if (typeof arg !== "string") {
      throw new TmuxRefusal(verb, "every argument must be a string");
    }
    if (arg.includes("\u0000")) {
      throw new TmuxRefusal(verb, "an argument contained a NUL byte");
    }
  }
  const explained = EXPLAINED_REFUSALS.get(verb);
  if (explained !== undefined) {
    throw new TmuxRefusal(verb, explained);
  }
  if (!ALLOWED_VERBS.has(verb)) {
    throw new TmuxRefusal(verb, "not a display-geometry command");
  }
}

/** The full argv handed to execFile, socket prefix included. Exported for assertions. */
export function buildArgv(args: readonly string[]): string[] {
  assertAllowedArgv(args);
  return ["-L", TMUX_SOCKET, ...args];
}

export interface TmuxResult {
  readonly stdout: string;
  readonly stderr: string;
}

/**
 * Run one tmux command. Rejects before spawning anything if the verb is not
 * permitted, so a refused call costs no process.
 */
export function tmux(args: readonly string[]): Promise<TmuxResult> {
  return new Promise<TmuxResult>((resolve, reject) => {
    // Inside the executor on purpose. A function typed Promise<T> that throws
    // synchronously escapes a caller's .catch() and takes the process down, so
    // the refusal is delivered as a rejection like every other failure here.
    // buildArgv still runs before execFile, so a refused call spawns nothing.
    const argv = buildArgv(args);
    execFile(
      "tmux",
      argv,
      {
        // No shell. The single most important option on this call.
        shell: false,
        timeout: TMUX_TIMEOUT_MS,
        maxBuffer: TMUX_MAX_BUFFER,
        windowsHide: true,
        encoding: "utf8",
      },
      (error, stdout, stderr) => {
        if (error !== null) {
          reject(error);
          return;
        }
        resolve({ stdout, stderr });
      },
    );
  });
}
