// The loopback bind, the health contract, and the proof that a route cannot opt
// out of validation.
//
// THE BIND IS ASSERTED THREE WAYS, because each alone can be satisfied by a server
// that is in fact listening on every interface:
//
//   1. what the listener reports        address() after listen()
//   2. what the OS says is listening    ss / netstat, filtered to this port
//   3. what is actually reachable       a real TCP connect on every non-loopback
//                                       address this machine has
//
// (3) is the one that cannot be faked. (2) is the literal "enumerate listening
// sockets", and it skips itself if neither tool exists rather than passing
// silently - a check that cannot run must not look like a check that passed.

import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir, networkInterfaces } from "node:os";
import { join } from "node:path";
import { connect } from "node:net";
import { execFileSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";

import { openStore } from "../src/db.ts";
import type { Store } from "../src/db.ts";
import { createServer, startServer } from "../src/server.ts";
import type { RunningServer } from "../src/server.ts";
import { API_HOST, API_PORT, REQUIRED_USER_VERSION } from "../src/config.ts";

let home: string;
let store: Store;
let running: RunningServer;

before(async () => {
  home = mkdtempSync(join(tmpdir(), "agentmux-api-srv-"));
  const path = join(home, "cc.db");
  const seed = new DatabaseSync(path);
  seed.exec("CREATE TABLE IF NOT EXISTS epics (id INTEGER PRIMARY KEY, title TEXT NOT NULL)");
  seed.exec(`PRAGMA user_version=${REQUIRED_USER_VERSION}`);
  seed.close();

  store = openStore({ dbPath: path });
  // Port 0, so the suite never contends for 8791 with a running API - and never
  // for 8787, which dashboard/server.py owns. The HOST is deliberately left at its
  // default: that default is the thing under test.
  running = await startServer({ store, port: 0 });
});

after(async () => {
  await running.stop();
  store.close();
  rmSync(home, { recursive: true, force: true });
});

describe("the listener is loopback only", () => {
  test("the default host is 127.0.0.1 and is not configurable", () => {
    assert.equal(API_HOST, "127.0.0.1");
    // No environment variable reads it. A setting that can be changed is a
    // setting that gets changed, and this one puts the operator's task store and
    // a tmux control channel on the LAN.
    assert.equal(process.env["AGENTMUX_API_HOST"], undefined);
  });

  test("the address the listener reports is loopback", () => {
    assert.equal(running.address, "127.0.0.1", "startServer bound something else");
    assert.ok(running.port > 0);
  });

  test("the OS listening-socket table shows only loopback for this port", { skip: sockets() === null ? "neither ss nor netstat is available" : false }, () => {
    const rows = sockets();
    assert.ok(rows !== null);
    const mine = rows.filter((row) => row.port === running.port);
    assert.ok(
      mine.length > 0,
      `the socket table does not show port ${running.port} at all - the filter is wrong, ` +
        "and a check that matches nothing always passes",
    );
    for (const row of mine) {
      assert.ok(
        row.address === "127.0.0.1" || row.address === "::1",
        `port ${running.port} is listening on ${row.address}, which is not loopback`,
      );
    }
  });

  test("no non-loopback address on this machine can reach it", async () => {
    const addresses: string[] = [];
    for (const list of Object.values(networkInterfaces())) {
      for (const iface of list ?? []) {
        if (!iface.internal && iface.family === "IPv4") {
          addresses.push(iface.address);
        }
      }
    }
    // Not a skip if the list is empty: a machine with no external interface
    // cannot demonstrate this, and saying so is more honest than passing.
    assert.ok(
      addresses.length > 0,
      "this host has no non-loopback IPv4 address, so reachability cannot be tested here",
    );

    // In parallel, and with a short timeout: a firewall that DROPS rather than
    // refuses makes each probe wait out the full timeout, and serially that is
    // several seconds per interface on a laptop with a dozen virtual adapters.
    const reachable = await Promise.all(
      addresses.map(async (address) => ({
        address,
        answered: await canConnect(address, running.port, 1000),
      })),
    );
    for (const result of reachable) {
      assert.equal(
        result.answered,
        false,
        `the API answered on ${result.address}:${running.port}`,
      );
    }
  });

  test("loopback itself DOES answer - the check above must not pass by being broken", async () => {
    assert.equal(await canConnect("127.0.0.1", running.port), true);
  });
});

describe("GET /health", () => {
  test("returns the whole contract, and nothing beyond it", async () => {
    const response = await running.app.inject({ method: "GET", url: "/health" });
    assert.equal(response.statusCode, 200);
    const body = response.json() as Record<string, unknown>;

    assert.deepEqual(
      Object.keys(body).sort(),
      ["boundAddress", "dbPath", "journalMode", "node", "ok", "userVersion"],
      "the health body grew or lost a field",
    );
    assert.equal(body["ok"], true);
    assert.equal(body["node"], process.version);
    assert.equal(body["dbPath"], store.dbPath);
    assert.equal(body["userVersion"], REQUIRED_USER_VERSION);
    assert.equal(body["journalMode"], "wal");
    assert.equal(body["boundAddress"], "127.0.0.1");
  });

  test("presence, never secrets", async () => {
    const response = await running.app.inject({ method: "GET", url: "/health" });
    const text = response.body;
    for (const forbidden of ["AGENTMUX_HOME", "token", "password", "authorization", "apiKey"]) {
      assert.ok(
        !text.toLowerCase().includes(forbidden.toLowerCase()),
        `/health leaked something named ${forbidden}`,
      );
    }
  });
});

describe("no handler can opt out of validation", () => {
  test("a route registered around the wrapper is refused AT BOOT", () => {
    const app = createServer({ store });
    assert.throws(
      () => {
        app.get("/sneaky", async () => ({ ok: true }));
      },
      /without the validating wrapper/,
      "app.get() went straight past the onRoute gate",
    );
  });

  test("the gate refuses a forged config object too", () => {
    const app = createServer({ store });
    assert.throws(() => {
      app.route({
        method: "GET",
        url: "/forged",
        // The marker is a module-private symbol in src/route.ts. It cannot be
        // imported, so this is the closest an outsider can get.
        config: { agentmuxRoute: "GET /forged", validated: true } as never,
        handler: async () => ({ ok: true }),
      });
    }, /without the validating wrapper/);
  });

  test("the wrapper's schema really runs - a strict empty query rejects extras", async () => {
    const response = await running.app.inject({ method: "GET", url: "/health?surprise=1" });
    assert.equal(response.statusCode, 400, "/health accepted a query string it declares nothing for");
    const body = response.json() as { ok: boolean; issues: { where: string }[] };
    assert.equal(body.ok, false);
    assert.ok(body.issues.length > 0);
    assert.equal(body.issues[0]?.where, "query");
  });

  test("the port is the strangler's temporary one, not the dashboard's", () => {
    // dashboard/server.py owns 8787 for the whole strangler. This moves at the
    // cutover (TM-039) and this assertion moves with it - deliberately, so the
    // cutover cannot happen by accident.
    assert.equal(API_PORT, 8791);
    assert.notEqual(API_PORT, 8787, "8787 belongs to dashboard/server.py until TM-039");
  });
});

interface ListeningSocket {
  readonly address: string;
  readonly port: number;
}

/** The OS listening-socket table, or null when neither tool is on this host. */
function sockets(): ListeningSocket[] | null {
  for (const [command, args] of [
    ["ss", ["-Hltn"]],
    ["netstat", ["-ano", "-p", "tcp"]],
  ] as const) {
    let output: string;
    try {
      output = execFileSync(command, [...args], { encoding: "utf8", timeout: 10_000 });
    } catch {
      continue;
    }
    const rows: ListeningSocket[] = [];
    for (const line of output.split("\n")) {
      if (!/LISTEN/i.test(line)) {
        continue;
      }
      // The local-address column in both tools: host:port, with an IPv6 host in
      // brackets. Take the last colon so ::1:8791 parses as port 8791.
      for (const field of line.trim().split(/\s+/)) {
        const at = field.lastIndexOf(":");
        if (at <= 0) {
          continue;
        }
        const port = Number(field.slice(at + 1));
        if (!Number.isInteger(port) || port <= 0) {
          continue;
        }
        rows.push({ address: field.slice(0, at).replace(/^\[|\]$/g, ""), port });
        break;
      }
    }
    return rows;
  }
  return null;
}

function canConnect(host: string, port: number, timeoutMs = 2000): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    const socket = connect({ host, port });
    const done = (answer: boolean): void => {
      socket.destroy();
      resolve(answer);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}
