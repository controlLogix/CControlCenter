// The Fastify app: loopback, validated routes, nothing else yet.
//
// PHASE 1.0/1.2 IS A SKELETON. No handler has been ported from
// dashboard/server.py and none will be until there is a differ that can run the
// same request against both servers and compare the answers. Porting first and
// verifying later is how a strangler quietly changes behaviour: the Python
// endpoint's exact status codes, error strings and field ordering are the
// contract, and "it looks right" is not a way to establish that they match.
// /health is here because it has no Python counterpart to differ against.

import Fastify from "fastify";
import type { FastifyInstance } from "fastify";
import { API_HOST, API_PORT } from "./config.ts";
import { enforceValidation, registerRoutes } from "./route.ts";
import { healthRoute } from "./routes/health.ts";
import type { Store } from "./db.ts";

/** Bounded body, as SPEC_CC.md:21-23 requires of every mutating endpoint. */
export const MAX_BODY_BYTES = 256 * 1024;

export interface ServerOptions {
  readonly store: Store;
  readonly host?: string;
  readonly port?: number;
}

export interface RunningServer {
  readonly app: FastifyInstance;
  /** The address the listener actually reports, not the one that was requested. */
  readonly address: string;
  readonly port: number;
  stop(): Promise<void>;
}

function addressOf(app: FastifyInstance): string | null {
  const address = app.server.address();
  if (address === null || typeof address === "string") {
    return address;
  }
  return address.address;
}

export function createServer(options: ServerOptions): FastifyInstance {
  const app = Fastify({
    logger: false,
    bodyLimit: MAX_BODY_BYTES,
    // Do not trust X-Forwarded-*. Nothing is meant to proxy this, and honouring
    // the header would let a request claim any client address it liked.
    trustProxy: false,
  });

  // FIRST, before any route. Fastify runs onRoute only for routes registered
  // after the hook is added, so this line being late is the same as it being
  // absent - and it would be absent invisibly, with every route still working.
  enforceValidation(app);

  registerRoutes(app, [
    healthRoute({
      store: options.store,
      boundAddress: () => addressOf(app),
    }),
  ]);

  return app;
}

/**
 * Bind and listen.
 *
 * host defaults to API_HOST and there is no environment variable for it. A test
 * may pass 127.0.0.1 with port 0 for an ephemeral port; nothing may pass a
 * non-loopback host, and test/server.test.ts proves the default is loopback by
 * trying to reach it on every other address this machine has.
 */
export async function startServer(options: ServerOptions): Promise<RunningServer> {
  const app = createServer(options);
  const host = options.host ?? API_HOST;
  const port = options.port ?? API_PORT;

  await app.listen({ host, port });

  const bound = app.server.address();
  if (bound === null || typeof bound === "string") {
    await app.close();
    throw new Error(`listener reported no TCP address (got ${String(bound)})`);
  }

  return {
    app,
    address: bound.address,
    port: bound.port,
    stop: async (): Promise<void> => {
      await app.close();
    },
  };
}
