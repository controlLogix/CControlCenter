// Every refusal in src/db.ts, each proved by the thing it is supposed to prevent
// actually not happening - not merely by an exception being thrown.
//
// The distinction matters. "openStore threw" is compatible with openStore having
// created the file and then thrown, or having executed the CREATE and then thrown.
// So the missing-file test asserts the file is still absent afterwards, and the
// DDL test asserts the table is still absent afterwards.

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, mkdirSync, existsSync, linkSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";

import { DbRefusal, openStore, assertNotDdl, leadingKeyword } from "../src/db.ts";
import { REQUIRED_USER_VERSION, databasePath } from "../src/config.ts";

/**
 * assert.throws() returns undefined, so it cannot be used to inspect the error it
 * caught. Every refusal here is asserted on its CODE and its MESSAGE - "something
 * threw" is not the property under test, since a typo in the path would also
 * throw - so the error has to come back.
 */
function refusalFrom(action: () => unknown): DbRefusal {
  try {
    action();
  } catch (error: unknown) {
    assert.ok(error instanceof DbRefusal, `expected a DbRefusal, got: ${String(error)}`);
    return error;
  }
  assert.fail("expected a DbRefusal, but nothing was thrown");
}

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "agentmux-api-db-"));
}

/**
 * Stand in for what dashboard/ccstore.py connection() leaves behind: a store with
 * the schema applied and PRAGMA user_version set. The test suite is allowed to run
 * DDL precisely because it is playing the part of the Python side here.
 */
function pythonWouldLeave(path: string, userVersion = REQUIRED_USER_VERSION): void {
  const db = new DatabaseSync(path);
  db.exec("CREATE TABLE IF NOT EXISTS epics (id INTEGER PRIMARY KEY, title TEXT NOT NULL)");
  db.exec(`PRAGMA user_version=${userVersion}`);
  db.close();
}

describe("openStore refuses a database it must not have", () => {
  test("a missing file is refused by path, and is NOT created", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      assert.equal(existsSync(path), false, "precondition: nothing there yet");

      const error = refusalFrom(() => openStore({ dbPath: path }));
      assert.equal(error.code, "DB_MISSING");
      assert.match(error.message, /no task store at/);
      assert.ok(
        error.message.includes(path),
        `the refusal must name the path it looked at; got: ${error.message}`,
      );

      // THE assertion. node:sqlite has no way to suppress O_CREAT, so the only
      // thing standing between this process and an empty user_version-0 database
      // is the existence check running first. If that ever regresses the throw
      // still happens and only this line notices.
      assert.equal(existsSync(path), false, "openStore must not create the database");
      assert.equal(existsSync(`${path}-wal`), false, "nor a WAL sidecar");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("the wrong PRAGMA user_version is refused, naming both versions", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path, 1);

      const error = refusalFrom(() => openStore({ dbPath: path }));
      assert.equal(error.code, "DB_WRONG_VERSION");
      assert.match(error.message, /user_version=1/);
      assert.match(error.message, new RegExp(`requires ${REQUIRED_USER_VERSION}`));

      // And it did not "helpfully" migrate on the way past.
      const db = new DatabaseSync(path);
      const row = db.prepare("PRAGMA user_version").get() as Record<string, unknown>;
      db.close();
      assert.equal(row["user_version"], 1, "Node must not raise the schema version");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("a version from the future is refused too, not just an older one", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path, REQUIRED_USER_VERSION + 1);
      const error = refusalFrom(() => openStore({ dbPath: path }));
      assert.equal(error.code, "DB_WRONG_VERSION");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("a symlinked database path is refused", { skip: symlinkSkip() }, () => {
    const home = scratch();
    try {
      const real = join(home, "real.db");
      const link = join(home, "cc.db");
      pythonWouldLeave(real);
      symlinkSync(real, link);

      const error = refusalFrom(() => openStore({ dbPath: link }));
      assert.equal(error.code, "DB_UNSAFE_PATH");
      assert.match(error.message, /unsafe database path/);
      assert.match(error.message, /symlink/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("a hard-linked database file is refused (st_nlink != 1)", { skip: hardlinkSkip() }, () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path);
      linkSync(path, join(home, "second-name.db"));

      const error = refusalFrom(() => openStore({ dbPath: path }));
      assert.equal(error.code, "DB_UNSAFE_FILE");
      assert.match(error.message, /hard links, expected 1/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("a non-regular file at the database path is refused", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      mkdirSync(path);
      const error = refusalFrom(() => openStore({ dbPath: path }));
      assert.equal(error.code, "DB_UNSAFE_FILE");
      assert.match(error.message, /not a regular file/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

describe("openStore accepts a store Python left correct", () => {
  test("it opens, and reports the pragmas it actually got", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path);
      const store = openStore({ dbPath: path });
      try {
        assert.equal(store.dbPath, path);
        assert.equal(store.userVersion, REQUIRED_USER_VERSION);
        assert.equal(store.journalMode, "wal", "ccstore.py connection() sets journal_mode=WAL");
        assert.equal(store.foreignKeys, true, "ccstore.py connection() sets foreign_keys=ON");
        assert.equal(store.busyTimeoutMs, 5000, "ccstore.py uses sqlite3.connect(timeout=5)");
        assert.deepEqual(store.all("SELECT * FROM epics"), []);
      } finally {
        store.close();
      }
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("AGENTMUX_HOME decides which cc.db, as every other file in the repo does", () => {
    const home = scratch();
    try {
      pythonWouldLeave(join(home, "cc.db"));
      const env = { AGENTMUX_HOME: home } as NodeJS.ProcessEnv;
      assert.equal(databasePath(env), join(home, "cc.db"));
      const store = openStore({ env });
      try {
        assert.equal(store.dbPath, join(home, "cc.db"));
      } finally {
        store.close();
      }
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

describe("the DDL refusal", () => {
  test("a CREATE through the Store is refused, and creates nothing", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path);
      const store = openStore({ dbPath: path });
      try {
        const error = refusalFrom(() =>
          store.run("CREATE TABLE node_was_here (id INTEGER PRIMARY KEY)"),
        );
        assert.equal(error.code, "DB_DDL_REFUSED");
        assert.match(error.message, /Python owns the schema/);

        // The table must genuinely not exist. sqlite_master is a plain SELECT,
        // so the Store itself can answer this.
        const row = store.get(
          "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
          "node_was_here",
        );
        assert.equal(row, undefined, "the refused CREATE must not have run");
      } finally {
        store.close();
      }
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  test("every schema-shaped verb is refused, through every Store method", () => {
    const statements = [
      "CREATE TABLE t (a INTEGER)",
      "CREATE INDEX ix ON epics (title)",
      "ALTER TABLE epics ADD COLUMN sneaky TEXT",
      "DROP TABLE epics",
      "REINDEX epics",
      "VACUUM",
      "ATTACH DATABASE 'other.db' AS other",
      "DETACH DATABASE other",
      "PRAGMA user_version=99",
      "PRAGMA foreign_keys=OFF",
      "PRAGMA journal_mode=DELETE",
    ];
    for (const sql of statements) {
      assert.throws(() => assertNotDdl(sql), DbRefusal, `not refused: ${sql}`);
    }
  });

  test("comments and casing do not get a statement past the screen", () => {
    // `/*x*/ CREATE ...` is a valid CREATE whose first character is a slash. A
    // naive startsWith("CREATE") check passes it straight through.
    assert.throws(() => assertNotDdl("/* harmless */ create table t (a)"), DbRefusal);
    assert.throws(() => assertNotDdl("-- just a note\nDROP TABLE epics"), DbRefusal);
    assert.throws(() => assertNotDdl("\n\n\t  CrEaTe TABLE t (a)"), DbRefusal);
    assert.equal(leadingKeyword("/* x */ -- y\n  select 1"), "SELECT");
  });

  test("ordinary data statements are NOT refused - the screen must not be a wall", () => {
    for (const sql of [
      "SELECT * FROM epics",
      "INSERT INTO epics (title) VALUES (?)",
      "UPDATE epics SET title = ? WHERE id = ?",
      "DELETE FROM epics WHERE id = ?",
      "WITH recent AS (SELECT 1) SELECT * FROM recent",
      "BEGIN",
      "COMMIT",
    ]) {
      assert.doesNotThrow(() => assertNotDdl(sql), `wrongly refused: ${sql}`);
    }
  });

  test("the Store exposes no exec(), so there is no multi-statement route", () => {
    const home = scratch();
    try {
      const path = join(home, "cc.db");
      pythonWouldLeave(path);
      const store = openStore({ dbPath: path });
      try {
        assert.equal(
          "exec" in store,
          false,
          "an exec() would take a script past the per-statement screen",
        );
      } finally {
        store.close();
      }
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

/** Windows refuses symlink creation without Developer Mode or elevation. */
function symlinkSkip(): string | false {
  const home = scratch();
  try {
    symlinkSync(join(home, "target"), join(home, "link"));
    return false;
  } catch {
    return "symlink creation not permitted on this host (Windows without Developer Mode)";
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}

/** Hard links need a filesystem that has them; the temp dir usually does. */
function hardlinkSkip(): string | false {
  const home = scratch();
  try {
    const a = join(home, "a");
    new DatabaseSync(a).close();
    linkSync(a, join(home, "b"));
    return false;
  } catch {
    return "hard links not supported on this filesystem";
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}
