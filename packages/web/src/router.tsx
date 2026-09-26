import {
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router';
import { AppShell } from '@/app/AppShell';
import { RAIL_VIEWS } from '@/app/Rail';
import { BoardView } from '@/views/BoardView';
import { StatusView } from '@/views/StatusView';
import { Placeholder } from '@/views/Placeholder';

/* A CODE-BASED route tree, not the file-route generator.
 *
 * The generator writes routeTree.gen.ts on a file watcher, which means a
 * generated file in the repo that must be regenerated to build. That is a fine
 * trade for an app with forty routes. This one has eight, all listed in
 * RAIL_VIEWS already, and the rail and the router reading the same array is
 * worth more here than the codegen: a view cannot exist in one and not the
 * other.
 */

const rootRoute = createRootRoute({ component: AppShell });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  // Status, not Terminals. Terminals is the loudest view; Status is the one
  // that answers "what is happening", which is what someone opening a console
  // is asking.
  beforeLoad: () => {
    throw redirect({ to: '/status' });
  },
});

const statusRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/status',
  component: StatusView,
});

const boardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/board',
  component: BoardView,
});

/* The other six are real routes with an honest placeholder rather than absent
 * routes. A rail item that navigates nowhere is indistinguishable from one that
 * is broken, and during a migration that ambiguity costs a bug report a week. */
const placeholderRoutes = RAIL_VIEWS.filter(
  (v) => !v.built,
).map((view) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path: view.path,
    component: () => <Placeholder label={view.label} hint={view.hint} />,
  }),
);

const routeTree = rootRoute.addChildren([
  indexRoute,
  statusRoute,
  boardRoute,
  ...placeholderRoutes,
]);

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
