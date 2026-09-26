// GET /health - presence, never secrets.
//
// WHAT IT IS FOR. During the strangler two servers answer for the same state:
// dashboard/server.py on 8787 and this one on API_PORT. When something is wrong
// the first question is always which process is being talked to, against which
// database, at which schema version. Every field here exists to answer one of
// those and nothing else.
//
//   node          which runtime. In WSL, "which node" is a live question -
//                 scripts/node-env.sh exists because the reachable one is the
//                 WINDOWS binary through /mnt interop.
//   dbPath        which cc.db. AGENTMUX_HOME makes this genuinely variable, and a
//                 dashboard reading a different home from the CLI is a bug this
//                 repo has already had (ccstore.py:HOME_DIR records it).
//   userVersion   which schema. Always REQUIRED_USER_VERSION if the process is up
//                 at all, since a mismatch refuses to boot - so this is a
//                 confirmation, not a check.
//   journalMode   that WAL actually took. It is persistent in the file, so a store
//                 that came back from a restore in `delete` mode would serve every
//                 read correctly and quietly serialise against the Python writer.
//   boundAddress  what the socket is really on, read back from the listener rather
//                 than echoed from configuration.
//
// WHAT IS NOT HERE, and why the docstring says "presence, never secrets": no
// environment, no token, no header, no connected-client list, no row counts. This
// endpoint takes no authentication, so everything it returns is public to anything
// that can reach the loopback port. dbPath is a path the operator already knows;
// it is the boundary, not an exception to it.

import { NOTHING, defineRoute } from "../route.ts";
import type { RouteRegistration } from "../route.ts";
import type { Store } from "../db.ts";

export interface HealthDependencies {
  readonly store: Store;
  /** Read back from the live listener, so it cannot disagree with reality. */
  readonly boundAddress: () => string | null;
}

export interface HealthBody {
  readonly ok: true;
  readonly node: string;
  readonly dbPath: string;
  readonly userVersion: number;
  readonly journalMode: string;
  readonly boundAddress: string | null;
}

export function healthRoute(dependencies: HealthDependencies): RouteRegistration {
  return defineRoute({
    method: "GET",
    url: "/health",
    schema: { params: NOTHING, query: NOTHING, body: NOTHING },
    handler: (): HealthBody => ({
      ok: true,
      node: process.version,
      dbPath: dependencies.store.dbPath,
      userVersion: dependencies.store.userVersion,
      journalMode: dependencies.store.journalMode,
      boundAddress: dependencies.boundAddress(),
    }),
  });
}
