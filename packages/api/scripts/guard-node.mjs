#!/usr/bin/env node
// Refuse a Node that resolves under /mnt/c, and say what to use instead.
//
// WHY THIS EXISTS. Measured on this host, 2026-09-25 (scripts/node-env.sh records
// the same measurement):
//
//     ~/.nvm/versions/node/v24.21.0   exists
//     command -v node                 -> nothing, in login AND non-interactive shells
//     command -v npm                  -> /mnt/c/Program Files/nodejs/npm
//
// nvm is installed and never sourced, so the only Node reachable from a
// non-interactive WSL shell is the WINDOWS one, leaking through /mnt/c interop.
// That is worse than having none. An `npm install` run under it builds native
// modules for the wrong platform, and the failures do not name their cause - you
// get a module that loads on neither side and an error about a missing binding.
//
// This package deliberately has no native dependency (node:sqlite is built in,
// precisely so there is nothing to rebuild per Node minor and nothing for
// node-gyp to do). That removes the worst outcome but not the confusion: a
// Windows Node in WSL still reports win32 paths, still resolves $HOME to the
// Windows profile in places, and still makes /health lie about where it is.
//
// So: fail at `npm start`, loudly, naming the nvm Node that is sitting right
// there unused. The discovery below is the same shape dashboard/test_e2e.sh:24-30
// and scripts/node-env.sh already use. One mechanism, not three.
//
// A native Windows Node running on Windows is FINE and is not what this guards.
// The bad case is specifically linux-in-WSL reaching back across the interop
// boundary, which is visible as an execPath under /mnt or /c.

import { realpathSync, existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const INTEROP_PREFIXES = ["/mnt/", "/c/", "/C/"];

/** True when `execPath` is a Windows binary reached through WSL's /mnt interop. */
export function isInteropNode(platform, execPath) {
  if (platform !== "linux") {
    return false;
  }
  return INTEROP_PREFIXES.some((prefix) => execPath.startsWith(prefix));
}

/**
 * Highest nvm Node, by VERSION sort rather than lexical: v9 must not beat v24.
 *
 * `env` is a parameter rather than a read of process.env, because it was one and
 * that was wrong. Sourcing scripts/node-env.sh exports AGENTMUX_NODE into the
 * environment, so this function ignored the `home` it was handed whenever it ran
 * after that - which is to say, whenever it ran inside the test suite this repo
 * actually uses. A function that silently overrides its own argument from a global
 * is one that cannot be tested and cannot be reasoned about; both inputs are now
 * inputs.
 */
export function findWslNode(home, env = process.env) {
  const override = env["AGENTMUX_NODE"];
  if (override !== undefined && override !== "" && existsSync(override)) {
    return override;
  }
  const versionsDir = join(home, ".nvm", "versions", "node");
  let entries;
  try {
    entries = readdirSync(versionsDir);
  } catch {
    return null;
  }
  const collator = new Intl.Collator(undefined, { numeric: true });
  const candidates = entries
    .map((name) => join(versionsDir, name, "bin", "node"))
    .filter((candidate) => existsSync(candidate))
    .sort(collator.compare);
  return candidates.length === 0 ? null : candidates[candidates.length - 1];
}

function main() {
  // realpath, because a symlink on PATH can point back across the boundary while
  // argv[0] looks perfectly native.
  let execPath = process.execPath;
  try {
    execPath = realpathSync(execPath);
  } catch {
    // Keep the unresolved path; an unreadable execPath is not a reason to pass.
  }

  if (!isInteropNode(process.platform, execPath)) {
    return 0;
  }

  const lines = [
    `@agentmux/api: refusing ${execPath} - that is the WINDOWS node, reached`,
    "  through /mnt interop. In WSL it reports win32-shaped paths, resolves the",
    "  wrong home directory, and makes /health report a machine you are not on.",
  ];
  const wslNode = findWslNode(homedir());
  if (wslNode === null) {
    lines.push(
      "  No Node found under ~/.nvm/versions/node either.",
      "  Install one:      nvm install 24",
      "  Or point at one:  export AGENTMUX_NODE=/path/to/bin/node",
    );
  } else {
    lines.push(
      `  There IS a usable Node in WSL, unused because nvm is never sourced:`,
      `      ${wslNode}`,
      `  Put it on PATH:   . scripts/node-env.sh   (from the repo root)`,
      `  Or directly:      PATH="$(dirname ${wslNode}):$PATH" npm start`,
    );
  }
  for (const line of lines) {
    console.error(line);
  }
  return 1;
}

// Only act when run directly; importing this for its predicates must be silent.
const invokedAs = process.argv[1];
if (invokedAs !== undefined && import.meta.url === pathToFileURL(invokedAs).href) {
  process.exit(main());
}
