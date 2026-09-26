import type { ComponentType, SVGProps } from 'react';
import { Link, useRouterState } from '@tanstack/react-router';
import {
  IconBoard,
  IconField,
  IconGit,
  IconOrg,
  IconRuns,
  IconSettings,
  IconStatus,
  IconTerminal,
} from './icons';

/* The left rail: eight views, icon only, 52px (--rail-width).
 *
 * Eight, in the order the vanilla dashboard already uses, because the two
 * frontends run side by side during the migration and a reordered rail is a
 * muscle-memory bug in a product people keep open all day. Settings is pushed
 * to the bottom by a spacer rather than by a second list, so adding a view is
 * one row here and nothing else.
 *
 * The active marker is a 1px orange left edge. Not a filled block: an orange
 * surface with nothing urgent behind it is precisely the misuse the accent-ramp
 * note in tokens.css exists to prevent.
 */

export interface RailView {
  path: string;
  label: string;
  hint: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** False for the six views still served by the vanilla dashboard. */
  built: boolean;
}

export const RAIL_VIEWS: readonly RailView[] = [
  { path: '/terminals', label: 'Terminals', hint: 'Live agent panes', Icon: IconTerminal, built: false },
  { path: '/status', label: 'Status', hint: 'Feed, queue, journal and chatter', Icon: IconStatus, built: true },
  { path: '/board', label: 'Board', hint: 'Epics, tasks and the tracker', Icon: IconBoard, built: true },
  { path: '/runs', label: 'Runs', hint: 'What is running, and what is waiting on you', Icon: IconRuns, built: false },
  { path: '/organization', label: 'Organization', hint: 'Agent definitions and task teams', Icon: IconOrg, built: false },
  { path: '/iiot', label: 'IIOT', hint: 'Modbus, PROFINET, MQTT, CODESYS targets', Icon: IconField, built: false },
  { path: '/github', label: 'GitHub', hint: 'Repositories, pull requests, workflow runs', Icon: IconGit, built: false },
  { path: '/settings', label: 'Settings', hint: 'Theme, motion, resources, configuration', Icon: IconSettings, built: false },
];

export function Rail() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <nav className="rail" aria-label="Views">
      <div className="rail-brand" title="agentmux">
        <span className="rail-mark" aria-hidden="true" />
        <span className="sr-only">agentmux</span>
      </div>

      <ul className="rail-list">
        {RAIL_VIEWS.map((view, i) => {
          const active = pathname.startsWith(view.path);
          return (
            <li key={view.path} className={i === RAIL_VIEWS.length - 1 ? 'rail-last' : undefined}>
              <Link
                to={view.path}
                className="rail-item t-colors"
                aria-current={active ? 'page' : undefined}
                data-active={active ? 'true' : 'false'}
                title={`${view.label} — ${view.hint}`}
              >
                <view.Icon />
                <span className="sr-only">{view.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
