import { Outlet, useRouterState } from '@tanstack/react-router';
import { Blade } from './Blade';
import { BladeProvider, useBlade } from './blade-state';
import { RAIL_VIEWS, Rail } from './Rail';
import './shell.css';

/* The shell: one CSS grid, three columns.
 *
 *     --rail-width | 1fr | blade
 *
 * The third column is 0 when the blade is hidden or floating, and
 * --blade-width when it is pinned. That is the entire mechanism by which
 * "pinned reflows" is true rather than claimed: the main region is a grid
 * track, so when the third track appears the second one genuinely narrows and
 * every ResizeObserver inside it fires. Nothing has to be told.
 *
 * The rail spans both rows so it is full height; the header sits over the main
 * region only, and the blade has its own head. That is what makes the blade
 * read as a second surface rather than as a drawer hanging off this one.
 */

function ShellFrame() {
  const blade = useBlade();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const view = RAIL_VIEWS.find((v) => pathname.startsWith(v.path));

  return (
    <div
      className="shell"
      data-blade={blade.state}
      style={{ ['--blade-width' as string]: `${blade.width}px` }}
    >
      <Rail />

      <header className="topbar">
        <span className="topbar-view">{view?.label ?? 'agentmux'}</span>
        <span className="topbar-hint">{view?.hint ?? ''}</span>
        <span className="topbar-spacer" />
        <button
          type="button"
          className="icon-btn t-colors pressable"
          onClick={() => blade.open()}
          aria-expanded={blade.state !== 'hidden'}
          aria-controls="blade"
          title="Detail panel (Ctrl+`)"
        >
          panel
        </button>
      </header>

      {/* key={pathname} restarts the .view-enter animation on a view change.
          That animation is a crossfade and a 4px lift, deliberately smaller
          than it wants to be: a view carrying a table must not appear to
          slide, because the rows are what the eye is trying to hold still. */}
      <main className="main" key={pathname}>
        <div className="view-enter view-scroll">
          <Outlet />
        </div>
      </main>

      <Blade />
    </div>
  );
}

export function AppShell() {
  return (
    <BladeProvider>
      <ShellFrame />
    </BladeProvider>
  );
}
