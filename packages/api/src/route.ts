// The one way a route gets registered, and the reason there is only one.
//
// WHAT THIS REPLACES. SPEC_CC.md:21-23 states the guard every mutating endpoint
// has to repeat:
//
//     Any mutating endpoint repeats the /api/resize guards: POST only,
//     Content-Type: application/json required (415), cross-origin Origin
//     rejected (403), bounded body, validated inputs.
//
// "Repeats" is the problem. That is a rule enforced by whoever writes the next
// handler remembering to write five things, in a 2,700-line file, under time
// pressure. It holds until it does not, and the endpoint that forgets looks
// exactly like the ones that did not.
//
// So validation here is structural rather than remembered. A RouteDefinition has
// no optional schema field - `params`, `query` and `body` are all required, and a
// route that genuinely takes no input has to say so with NOTHING, which is a
// STRICT empty object and therefore still rejects anything that arrives. There is
// no shape of this type that means "skip validation".
//
// And because a determined handler could still reach past this module and call
// app.get() directly, enforceValidation() installs an onRoute hook that fires for
// every route Fastify accepts and throws on any that did not come through here.
// The marker it looks for is a module-private symbol, so it cannot be forged from
// outside this file - you cannot import it. The failure is at registration, at
// boot, not on the first request from a user.

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";
import type { ZodType } from "zod";

/**
 * For a route that takes no input. STRICT on purpose: an endpoint that accepts
 * nothing should reject a request that sends something, rather than quietly
 * ignoring it. A stray field is usually a caller who thinks this endpoint does
 * more than it does, and silence is how that survives to production.
 */
export const NOTHING = z.object({}).strict();

export type RouteMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RouteSchema<P, Q, B> {
  readonly params: ZodType<P>;
  readonly query: ZodType<Q>;
  readonly body: ZodType<B>;
}

export interface RouteInput<P, Q, B> {
  readonly params: P;
  readonly query: Q;
  readonly body: B;
}

export interface RouteContext {
  readonly request: FastifyRequest;
  readonly reply: FastifyReply;
}

export interface RouteDefinition<P, Q, B, R> {
  readonly method: RouteMethod;
  readonly url: string;
  readonly schema: RouteSchema<P, Q, B>;
  readonly handler: (input: RouteInput<P, Q, B>, context: RouteContext) => R | Promise<R>;
}

/**
 * A route definition with its generics erased, so a heterogeneous list of routes
 * has a type. Erasure happens inside defineRoute, where the generics are still
 * known and checked - nothing is cast away at the call site and nothing is `any`.
 */
export interface RouteRegistration {
  readonly method: RouteMethod;
  readonly url: string;
  register(app: FastifyInstance): void;
}

// Module-private. Not exported, cannot be imported, therefore cannot be forged by
// a handler that wants to skip validation. Symbol-keyed so it survives the shallow
// copies Fastify makes of a route's config on the way to the request context.
const VALIDATED = Symbol("agentmux.route.validated");

interface ValidationIssue {
  readonly where: "params" | "query" | "body";
  readonly path: string;
  readonly message: string;
}

function collect(where: ValidationIssue["where"], error: z.ZodError): ValidationIssue[] {
  return error.issues.map((issue) => ({
    where,
    path: issue.path.join("."),
    message: issue.message,
  }));
}

export function defineRoute<P, Q, B, R>(definition: RouteDefinition<P, Q, B, R>): RouteRegistration {
  return {
    method: definition.method,
    url: definition.url,
    register(app: FastifyInstance): void {
      // Built as a variable rather than inline so the symbol key is not caught by
      // TypeScript's excess-property check on object literals.
      const config: Record<string | symbol, unknown> = {
        [VALIDATED]: true,
        agentmuxRoute: `${definition.method} ${definition.url}`,
      };

      app.route({
        method: definition.method,
        url: definition.url,
        config: config as never,
        handler: async (request: FastifyRequest, reply: FastifyReply): Promise<unknown> => {
          // `?? {}` on all three: Fastify leaves body undefined on a GET and
          // params empty for a static route, and a strict empty object schema
          // rejects undefined. Normalising here means NOTHING behaves the way its
          // name promises instead of failing every GET.
          const params = definition.schema.params.safeParse(request.params ?? {});
          const query = definition.schema.query.safeParse(request.query ?? {});
          const body = definition.schema.body.safeParse(request.body ?? {});

          const issues: ValidationIssue[] = [
            ...(params.success ? [] : collect("params", params.error)),
            ...(query.success ? [] : collect("query", query.error)),
            ...(body.success ? [] : collect("body", body.error)),
          ];
          if (issues.length > 0) {
            await reply.code(400).send({ ok: false, error: "invalid request", issues });
            return reply;
          }
          if (!params.success || !query.success || !body.success) {
            // Unreachable: issues would be non-empty. Present so the narrowing
            // below needs no non-null assertion.
            await reply.code(400).send({ ok: false, error: "invalid request", issues });
            return reply;
          }

          return definition.handler(
            { params: params.data, query: query.data, body: body.data },
            { request, reply },
          );
        },
      });
    },
  };
}

/**
 * Install the gate. Call this before registering anything: Fastify only runs an
 * onRoute hook for routes added AFTER the hook, so a hook installed late silently
 * covers nothing, which is the one failure mode this design cannot tolerate.
 */
export function enforceValidation(app: FastifyInstance): void {
  app.addHook("onRoute", (routeOptions) => {
    const config: unknown = routeOptions.config;
    const marked =
      typeof config === "object" &&
      config !== null &&
      (config as Record<symbol, unknown>)[VALIDATED] === true;
    if (!marked) {
      throw new Error(
        `route ${String(routeOptions.method)} ${routeOptions.url} was registered ` +
          "without the validating wrapper. Every route goes through defineRoute() " +
          "in src/route.ts, which requires a Zod schema for params, query and body. " +
          "A route that takes no input passes NOTHING - there is no opt-out.",
      );
    }
  });
}

/** Register a list of routes, in order. */
export function registerRoutes(app: FastifyInstance, routes: readonly RouteRegistration[]): void {
  for (const route of routes) {
    route.register(app);
  }
}
