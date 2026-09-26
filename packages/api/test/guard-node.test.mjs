// The prestart guard. Plain .mjs, matching the file it tests - the guard must run
// on any Node at all, including one too old for type stripping, so it has no
// build step and neither does this.

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { isInteropNode, findWslNode } from "../scripts/guard-node.mjs";

describe("the Windows-node-in-WSL guard", () => {
  test("a Windows node reached through /mnt interop is refused", () => {
    // The measured case: command -v npm in WSL returns this.
    assert.equal(isInteropNode("linux", "/mnt/c/Program Files/nodejs/node.exe"), true);
    assert.equal(isInteropNode("linux", "/mnt/c/Program Files/nodejs/node"), true);
    assert.equal(isInteropNode("linux", "/c/Program Files/nodejs/node.exe"), true);
  });

  test("a real WSL node is not refused", () => {
    assert.equal(isInteropNode("linux", "/home/nick/.nvm/versions/node/v24.21.0/bin/node"), false);
    assert.equal(isInteropNode("linux", "/usr/bin/node"), false);
  });

  test("Windows running its own node natively is NOT what this guards", () => {
    // Running npm from Windows PowerShell is the documented way to install this
    // package. A guard that refused that would be worse than no guard.
    assert.equal(isInteropNode("win32", "C:\\Program Files\\nodejs\\node.exe"), false);
    assert.equal(isInteropNode("darwin", "/usr/local/bin/node"), false);
  });
});

describe("the nvm discovery", () => {
  test("picks the highest version by VERSION order, not lexical", () => {
    const home = mkdtempSync(join(tmpdir(), "agentmux-guard-"));
    try {
      // Lexically, "v9.11.2" sorts after "v24.21.0". This is the bug
      // scripts/node-env.sh uses `sort -V` to avoid, and the reason the guard
      // uses a numeric collator rather than a plain sort.
      for (const version of ["v9.11.2", "v18.20.4", "v24.21.0"]) {
        const bin = join(home, ".nvm", "versions", "node", version, "bin");
        mkdirSync(bin, { recursive: true });
        writeFileSync(join(bin, "node"), "");
      }
      const found = findWslNode(home, {});
      assert.ok(found !== null, "nothing found where three versions were planted");
      assert.ok(found.includes("v24.21.0"), `picked ${found}, expected v24.21.0`);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("returns null rather than guessing when nvm is not installed", () => {
    const home = mkdtempSync(join(tmpdir(), "agentmux-guard-empty-"));
    try {
      // An explicit empty environment. This test failed on its first run in WSL,
      // for a good reason: findWslNode read process.env directly, and the suite
      // runs after scripts/node-env.sh has exported AGENTMUX_NODE - so the
      // function ignored the empty home it was given and returned the operator's
      // real node. The fix was to make the environment a parameter.
      assert.equal(findWslNode(home, {}), null);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("an explicit AGENTMUX_NODE wins, so a different layout needs no edit", () => {
    const home = mkdtempSync(join(tmpdir(), "agentmux-guard-override-"));
    try {
      const custom = join(home, "custom-node");
      writeFileSync(custom, "");
      assert.equal(findWslNode(home, { AGENTMUX_NODE: custom }), custom);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("an AGENTMUX_NODE pointing at nothing is ignored, not trusted", () => {
    const home = mkdtempSync(join(tmpdir(), "agentmux-guard-stale-"));
    try {
      const bin = join(home, ".nvm", "versions", "node", "v24.21.0", "bin");
      mkdirSync(bin, { recursive: true });
      writeFileSync(join(bin, "node"), "");
      const found = findWslNode(home, { AGENTMUX_NODE: join(home, "was-deleted") });
      assert.ok(found?.includes("v24.21.0"), `a stale override was believed: ${found}`);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
