import {
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router';
import type { FunctionComponent } from 'react';
import { AppShell } from '@/app/AppShell';
import { RAIL_VIEWS } from '@/app/Rail';
import { Placeholder } from '@/views/Placeholder';

/* A CODE-BASED route tree, DISCOVERED rather than hand-listed.
 *
 * WHY IT CHANGED. It used to import each view explicitly, which is the clearer
 * thing to read and was correct while one person was porting one view at a
 * time. It stopped being correct the moment the eight remaining views were
 * split across a team: every one of those ports has to register its route, so
 * every one of them edits THIS FILE, and eight agents editing one file is eight
 * conflicts on the one file that breaks the whole app when it is merged wrong.
 *
 * RULE #-0.7 says to split work by FILE so claims cannot overlap. This is that
 * split, made structural: a view now owns `src/views/<name>/` entirely and
 * nothing else, and it appears in the router by EXISTING rather than by being
 * added to a list.
 *
 * THE CONVENTION. A ported view provides:
 *
 *     src/views/<name>/route.tsx
 *       export const path = '/iiot';            // must match its RAIL_VIEWS path
 *       export default function IiotView() {...}
 *
 * import.meta.glob is eager and compile-time, so this stays a static import
 * graph - Vite resolves it at build, there is no runtime directory read, and a
 * view that fails to compile fails the build rather than blanking at runtime.
 *
 * `built` in RAIL_VIEWS is now DERIVED from whether a route module exists,
 * instead of being a flag someone has to remember to flip. A view that is
 * ported but still marked unbuilt would render its own placeholder over working
 * code, which is the kind of contradiction that costs an afternoon.
 */

interface ViewModule {
  path?: string;
  /* A FUNCTION component specifically, not ComponentType. ComponentType also
   * admits a class component, which TanStack's RouteComponent does not accept -
   * and the resulting error names a type mismatch rather than the real rule,
   * which is "views here are function components". Saying so in the type means
   * a class component fails at the view that wrote it, not at the router. */
  default: FunctionComponent;
}

const modules = import.meta.glob<ViewModule>('./views/*/route.tsx', { eager: true });

/** '/iiot' -> the module that claims it. Keyed by path, not by directory name,
 *  so a directory renamed without its path changing cannot silently unregister
 *  a view. */
const discovered = new Map<string, ViewModule>();
for (const [file, mod] of Object.entries(modules)) {
  // Fall back to the directory name so a module that forgets to export `path`
  // still lands somewhere sensible rather than vanishing.
  const dir = file.split('/').at(-2) ?? '';
  const routePath = mod.path ?? `/${dir}`;
  if (discovered.has(routePath)) {
    // Two modules claiming one path is a merge accident. Fail loudly at build
    // rather than letting whichever one Vite enumerated last silently win.
    throw new Error(
      `Two view modules both claim ${routePath}. One of them is a bad merge: ${file}`,
    );
  }
  discovered.set(routePath, mod);
}

export const DISCOVERED_VIEW_PATHS: readonly string[] = [...discovered.keys()];

/* The landing path, asserted rather than assumed. Discovery cost the compiler's
 * knowledge of which paths exist (see the redirect below), so this replaces it:
 * if Status is ever renamed or dropped from the rail, the build fails here
 * instead of every visit to '/' redirecting into a 404. */
const LANDING = '/status';
if (!RAIL_VIEWS.some((v) => v.path === LANDING)) {
  throw new Error(
    `The landing redirect points at ${LANDING}, which is not in RAIL_VIEWS. ` +
      'Point it at a view that exists.',
  );
}

const rootRoute = createRootRoute({ component: AppShell });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  // Status, not Terminals. Terminals is the loudest view; Status is the one
  // that answers "what is happening", which is what someone opening a console
  // is asking.
  beforeLoad: () => {
    /* Cast for the same reason as the route paths below, and it is the price of
     * discovery: with a hand-listed tree TanStack knew every path as a literal
     * and would have caught a typo here at compile time. It cannot any more.
     * What replaces that check is the assertion below - '/status' must be a
     * RAIL_VIEWS path - which fails the build rather than redirecting a person
     * into a 404. */
    throw redirect({ to: '/status' as '/' });
  },
});

/* Every rail entry becomes a real route. A ported view gets its component; one
 * that is not ported yet gets an honest placeholder, because a rail item that
 * navigates nowhere is indistinguishable from one that is broken, and during a
 * migration that ambiguity costs a bug report a week. */
const viewRoutes = RAIL_VIEWS.map((view) => {
  const mod = discovered.get(view.path);
  const Component = mod
    ? mod.default
    : () => <Placeholder label={view.label} hint={view.hint} />;
  return createRoute({
    getParentRoute: () => rootRoute,
    /* TanStack infers a literal union from the path, which a value read out of
     * an array cannot satisfy. The cast is safe for a reason worth stating
     * rather than assuming: RAIL_VIEWS is the ONLY source of these paths, the
     * orphan check below rejects any module claiming a path not in it, and the
     * duplicate check above rejects two modules claiming one path. So the set
     * of paths reaching this line is exactly the set declared in the rail. */
    path: view.path as '/',
    component: Component,
  });
});

/* A module for a path the rail does not know about would be unreachable and
 * invisible - the view exists, compiles, and nobody can get to it. Say so. */
const orphans = [...discovered.keys()].filter(
  (p) => !RAIL_VIEWS.some((v) => v.path === p),
);
if (orphans.length) {
  throw new Error(
    `These view modules have no rail entry, so nothing can navigate to them: ${orphans.join(', ')}. ` +
      'Add them to RAIL_VIEWS in src/app/Rail.tsx.',
  );
}

const routeTree = rootRoute.addChildren([indexRoute, ...viewRoutes]);

export const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  /* A view swap is a crossfade of about half a second (--dur-slow). Holding the
   * outgoing view for that long on a slow load would make navigation feel
   * broken, so pending is shown immediately and the fade does the softening. */
  defaultPendingMs: 0,
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
