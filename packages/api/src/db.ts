// The connection to the task store, opened exactly as dashboard/ccstore.py does,
// with one deliberate difference: Node never writes schema and never creates the
// file.
//
// WHY NODE NEVER RUNS DDL. Python owns migrations for the whole strangler.
// ccstore.py connection() replays SCHEMA and ccboard.migrate on EVERY connection,
// on purpose - a database restored from backup, or one a second checkout created,
// arrives correct rather than half-built. That only works while exactly one
// process decides what "correct" means. The moment Node also creates tables, two
// programs are racing to define the same schema, and the loser's version is
// whichever opened second. The failure would not be a crash; it would be a column
// that exists on one developer's machine and not another's.
//
// So the split is: Python migrates, Node asserts. This module refuses to start
// against a database it does not recognise, and the Store it returns refuses DDL
// at the point of execution rather than trusting every future handler to behave.
//
// WHY node:sqlite AND NOT better-sqlite3. better-sqlite3 is a native addon: it
// needs a C++ toolchain and a rebuild for every Node minor. This same checkout is
// opened from Windows AND from WSL, so a native build is not built once - it is
// built twice, for two platforms, into one shared node_modules, and whichever side
// built last is the only side that works. node:sqlite is in the runtime. Nothing
// to compile, nothing for node-gyp to do, nothing to get wrong per platform.

import { DatabaseSync } from "node:sqlite";
import { lstatSync } from "node:fs";
import { BUSY_TIMEOUT_MS, REQUIRED_USER_VERSION, databasePath } from "./config.ts";

/** Every refusal from this module, so a caller can tell them apart. */
export type DbRefusalCode =
  | "DB_MISSING"
  | "DB_UNSAFE_PATH"
  | "DB_UNSAFE_FILE"
  | "DB_WRONG_VERSION"
  | "DB_DDL_REFUSED";

export class DbRefusal extends Error {
  readonly code: DbRefusalCode;
  readonly dbPath: string | undefined;

  constructor(code: DbRefusalCode, message: string, dbPath?: string) {
    super(message);
    this.name = "DbRefusal";
    this.code = code;
    this.dbPath = dbPath;
  }
}

// The leading keywords that change the shape of the database rather than its
// contents. ATTACH and DETACH are here because they bring a second file's schema
// into scope, which is the same problem wearing a different hat.
const DDL_KEYWORDS: ReadonlySet<string> = new Set([
  "CREATE",
  "ALTER",
  "DROP",
  "REINDEX",
  "VACUUM",
  "ATTACH",
  "DETACH",
  "PRAGMA",
]);

/**
 * Strip leading whitespace and SQL comments, then return the first bare word,
 * upper-cased. Comments are stripped because `/*x*\/ CREATE TABLE ...` is a
 * perfectly valid CREATE whose first character is a slash.
 */
export function leadingKeyword(sql: string): string {
  let rest = sql;
  for (;;) {
    const before = rest;
    rest = rest.replace(/^\s+/, "");
    rest = rest.replace(/^--[^\n]*(\n|$)/, "");
    rest = rest.replace(/^\/\*[\s\S]*?\*\//, "");
    if (rest === before) {
      break;
    }
  }
  const match = /^[A-Za-z_]+/.exec(rest);
  return match === null ? "" : match[0].toUpperCase();
}

/**
 * The DDL refusal. Throws unless `sql` is a data statement.
 *
 * PRAGMA is refused wholesale rather than only its writing forms. A read like
 * `PRAGMA user_version` is harmless, but telling `PRAGMA foreign_keys` from
 * `PRAGMA foreign_keys=OFF` by parsing is exactly the kind of almost-right check
 * that eventually lets the wrong one through. The three pragmas this API needs are
 * applied once at open() and reported by /health, so no handler has a reason to
 * ask for another.
 */
export function assertNotDdl(sql: string): void {
  const keyword = leadingKeyword(sql);
  if (DDL_KEYWORDS.has(keyword)) {
    throw new DbRefusal(
      "DB_DDL_REFUSED",
      `refusing to execute ${keyword}: Python owns the schema for the whole ` +
        "strangler (dashboard/ccstore.py SCHEMA and ccboard.migrate). Node " +
        "asserts PRAGMA user_version and never migrates. If this statement is " +
        "really needed, add it on the Python side and raise the version there.",
    );
  }
}

/** What a row looks like coming out of node:sqlite. */
export type Row = Record<string, unknown>;

/**
 * The only handle handlers get. It has no `exec`, so there is no route from
 * application code to a multi-statement script, and every single statement it
 * does accept is screened for DDL first.
 */
export interface Store {
  readonly dbPath: string;
  readonly userVersion: number;
  readonly journalMode: string;
  readonly foreignKeys: boolean;
  readonly busyTimeoutMs: number;
  all(sql: string, ...params: readonly unknown[]): Row[];
  get(sql: string, ...params: readonly unknown[]): Row | undefined;
  run(sql: string, ...params: readonly unknown[]): { changes: number | bigint };
  close(): void;
}

function readScalar(db: DatabaseSync, sql: string): unknown {
  const row = db.prepare(sql).get() as Row | undefined;
  if (row === undefined) {
    return undefined;
  }
  const values = Object.values(row);
  return values.length === 0 ? undefined : values[0];
}

/**
 * Port of dashboard/ccstore.py connection() path safety, verbatim in behaviour.
 *
 *     if DB_PATH.is_symlink():            raise OSError("unsafe database path")
 *     if DB_PATH.exists():
 *         info = DB_PATH.lstat()
 *         if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
 *             raise OSError("unsafe database file")
 *
 * WHAT THE TWO CHECKS ARE FOR, because they read like paranoia and are not.
 *
 *   symlink     ~/.agentmux is a directory the operator, the test suites and any
 *               agent can all write to. A symlink planted at cc.db redirects every
 *               read AND every write to a file of someone else's choosing, and
 *               nothing in the normal operation of the dashboard would show it.
 *               SQLite follows it happily.
 *
 *   st_nlink    A hard link is the same attack without a symlink's visibility -
 *               `ls -l` shows an ordinary file. It also breaks the thing operators
 *               rely on to recover: deleting or replacing cc.db leaves the other
 *               link, and therefore the data, exactly where it was. A regular
 *               database file has exactly one name.
 *
 * The ONE deliberate divergence from the Python: ccstore.py does
 * `DB_PATH.parent.mkdir(parents=True, exist_ok=True)` first and tolerates the file
 * being absent, because Python is allowed to create the store. Node is not, so a
 * missing file is a refusal here rather than a creation.
 */
export function assertSafeDatabasePath(dbPath: string): void {
  let info;
  try {
    info = lstatSync(dbPath);
  } catch (error: unknown) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT" || code === "ENOTDIR") {
      throw new DbRefusal(
        "DB_MISSING",
        `no task store at ${dbPath}. This API never creates it: the schema is ` +
          "Python's (dashboard/ccstore.py), and a database created here would be " +
          "an empty one at user_version 0 that then has to be told apart from a " +
          "real one. Start the Python dashboard once, or point AGENTMUX_HOME at " +
          "the home that already has a cc.db.",
        dbPath,
      );
    }
    throw error;
  }

  if (info.isSymbolicLink()) {
    throw new DbRefusal("DB_UNSAFE_PATH", `unsafe database path: ${dbPath} is a symlink`, dbPath);
  }
  if (!info.isFile()) {
    throw new DbRefusal(
      "DB_UNSAFE_FILE",
      `unsafe database file: ${dbPath} is not a regular file`,
      dbPath,
    );
  }
  if (info.nlink !== 1) {
    throw new DbRefusal(
      "DB_UNSAFE_FILE",
      `unsafe database file: ${dbPath} has ${info.nlink} hard links, expected 1`,
      dbPath,
    );
  }
}

export interface OpenOptions {
  readonly dbPath?: string;
  readonly env?: NodeJS.ProcessEnv;
}

/**
 * Open the task store, or refuse and explain why.
 *
 * Order matters. The path safety runs BEFORE the connection, because
 * DatabaseSync creates the file it is pointed at - node:sqlite exposes no way to
 * suppress that, there is no O_CREAT flag on the constructor. The existence check
 * is therefore the mechanism that keeps this process from bringing an empty
 * database into being, not a nicety in front of one.
 *
 * That check is not atomic, so the path is re-verified after the open: if the file
 * were swapped in between, the second lstat sees it. And behind both, the
 * user_version assertion is a third net - a file this process created would read 0
 * and be refused on the spot.
 */
export function openStore(options: OpenOptions = {}): Store {
  const dbPath = options.dbPath ?? databasePath(options.env ?? process.env);

  assertSafeDatabasePath(dbPath);

  const db = new DatabaseSync(dbPath, {
    enableForeignKeyConstraints: true,
    timeout: BUSY_TIMEOUT_MS,
  });

  try {
    // Re-check after the open. Cheap, and it closes the window between the lstat
    // above and the file the connection actually got.
    assertSafeDatabasePath(dbPath);

    // The pragmas, as ccstore.py connection() sets them. journal_mode is
    // persistent in the file and foreign_keys is per-connection, so this is not
    // redundant with whatever Python did - the second one has to be said here or
    // it is not true here.
    //
    // Each is READ BACK rather than assumed. journal_mode in particular can
    // refuse: a store restored in `delete` mode with a reader attached stays in
    // `delete`, every query still works, and the only symptom is that this
    // process and the Python one start serialising against each other. Reading
    // the result means /health reports what the connection got, not what it
    // asked for.
    db.exec(`PRAGMA busy_timeout=${BUSY_TIMEOUT_MS}`);
    const busyTimeoutMs = Number(readScalar(db, "PRAGMA busy_timeout") ?? 0);
    const journalMode = String(readScalar(db, "PRAGMA journal_mode=WAL") ?? "");
    db.exec("PRAGMA foreign_keys=ON");
    const foreignKeys = Number(readScalar(db, "PRAGMA foreign_keys") ?? 0) === 1;

    const userVersion = Number(readScalar(db, "PRAGMA user_version") ?? -1);
    if (userVersion !== REQUIRED_USER_VERSION) {
      throw new DbRefusal(
        "DB_WRONG_VERSION",
        `${dbPath} is at PRAGMA user_version=${userVersion}, this build requires ` +
          `${REQUIRED_USER_VERSION}. Node does not migrate - dashboard/ccstore.py ` +
          "connection() does, on every connection. Open the store once from the " +
          "Python side and it will be brought up; if it reports a version this " +
          "build has never heard of, this build is the old one.",
        dbPath,
      );
    }

    const store: Store = {
      dbPath,
      userVersion,
      journalMode,
      foreignKeys,
      busyTimeoutMs,
      all(sql: string, ...params: readonly unknown[]): Row[] {
        assertNotDdl(sql);
        return db.prepare(sql).all(...(params as never[])) as Row[];
      },
      get(sql: string, ...params: readonly unknown[]): Row | undefined {
        assertNotDdl(sql);
        return db.prepare(sql).get(...(params as never[])) as Row | undefined;
      },
      run(sql: string, ...params: readonly unknown[]): { changes: number | bigint } {
        assertNotDdl(sql);
        const result = db.prepare(sql).run(...(params as never[]));
        return { changes: result.changes };
      },
      close(): void {
        db.close();
      },
    };
    return store;
  } catch (error: unknown) {
    db.close();
    throw error;
  }
}
