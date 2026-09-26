import { homedir } from "node:os";
import { join } from "node:path";

/**
 * The port this API listens on.
 *
 * NOT 8787. dashboard/server.py owns 8787 and will keep owning it for the whole
 * strangler: the operator's dashboard, dashboard/restart.sh, the flock in
 * dashboard/run_tests.sh and every frontend fetch all assume it. 8789 is taken on
 * this host as well, so the skeleton parks on 8791.
 *
 * This moves to 8787 at the strangler cutover (TM-039), when server.py stops
 * binding it. That is the ONLY reason this is a named constant rather than an
 * inline literal - when the cutover happens it must be one edit, in one place,
 * and every test must follow it automatically.
 */
export const API_PORT = 8791;

/**
 * Loopback only, always.
 *
 * SPEC_CC.md lists "Bind 127.0.0.1 only" as a standing constraint inherited from
 * the existing dashboard, and it is a real one: this process reads the operator's
 * task store and shells out to tmux. Binding 0.0.0.0 would put both on the LAN.
 * There is no environment variable for this on purpose - a setting that can be
 * changed is a setting that gets changed.
 */
export const API_HOST = "127.0.0.1";

/**
 * Busy timeout, in milliseconds.
 *
 * dashboard/ccstore.py connection() uses sqlite3.connect(DB_PATH, timeout=5),
 * which is 5 seconds. Both processes hold the same WAL database open, so the two
 * must agree - a shorter timeout here would turn ordinary contention with the
 * Python writer into SQLITE_BUSY errors that look like corruption.
 */
export const BUSY_TIMEOUT_MS = 5000;

/**
 * The schema version this build understands.
 *
 * Python owns migrations for the entire strangler (dashboard/ccstore.py SCHEMA
 * plus ccboard.migrate). Node asserts and never migrates, so this number is a
 * statement about what Node was written against, not a target to migrate toward.
 */
export const REQUIRED_USER_VERSION = 2;

/**
 * AGENTMUX_HOME, as everything else in this repo already honours it.
 *
 * ccstore.py:HOME_DIR carries the history: agentmux.sh, courier.py, coordination.py
 * and run.py all resolve their root this way, and the two files that hardcoded
 * ~/.agentmux made the CLI and the dashboard silently read DIFFERENT directories
 * the moment a test suite set the variable. Reading it here is not a convenience,
 * it is the only way this API and the Python server agree on which database they
 * are both talking about.
 */
export function homeDir(env: NodeJS.ProcessEnv = process.env): string {
  const override = env["AGENTMUX_HOME"];
  if (override !== undefined && override !== "") {
    return override;
  }
  return join(homedir(), ".agentmux");
}

/** The task store, as dashboard/ccstore.py:DB_PATH resolves it. */
export function databasePath(env: NodeJS.ProcessEnv = process.env): string {
  return join(homeDir(env), "cc.db");
}
