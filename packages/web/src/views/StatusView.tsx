import { useEffect, useMemo, useState } from 'react';
import { useBlade } from '@/app/blade-state';
import { Card, LiveChip, SeverityDot, StatusPill, ViewHeader } from '@/components/ui';
import { Value } from '@/components/Value';
import { agentLiveness, readingLiveness, STALE_AFTER_MS } from '@/lib/freshness';
import { clock, relativeAge, uptime } from '@/lib/format';
import { useReveals } from '@/motion/useReveals';
import {
  fetchAgents,
  fetchFeed,
  fetchStatus,
  type Agent,
  type FeedEntry,
  type FeedSeverity,
  type StatusSnapshot,
} from '@/mock';
import './status.css';

/* Status — what is happening, and how long ago we last checked.
 *
 * Three bands: counters, live chips, feed. The motion is doing exactly one job
 * in each, and in each case it is a job about STRUCTURE rather than about data:
 *
 *   counters   [data-reveal] on the cards + [data-stagger] on their row. The
 *              cards arrive in sequence so the eye gets an order to read them
 *              in. The NUMBERS inside never animate - see components/Value.tsx.
 *   chips      Same stagger. The pulse on a chip is gated on data-live, and
 *              data-live is computed in lib/freshness from a measured
 *              observation, never from the fact that a chip exists.
 *   feed       The panel reveals as ONE block, and the rows do not. A row that
 *              is still arriving is indistinguishable from a row that has not
 *              loaded, and a feed is the one surface where that ambiguity
 *              actually costs something.
 */

const SEVERITY_ORDER: readonly FeedSeverity[] = ['info', 'warn', 'error'];

export function StatusView() {
  const blade = useBlade();
  const [status, setStatus] = useState<StatusSnapshot | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  const [minSeverity, setMinSeverity] = useState<FeedSeverity>('info');

  /* A clock that ticks so ages stay true. It is the only thing on this view
   * that re-renders on a timer, and it re-renders TEXT that is recomputed from
   * a timestamp - not a value that is being interpolated toward a target. */
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchStatus(), fetchAgents(), fetchFeed()]).then(([s, a, f]) => {
      if (cancelled) return;
      setStatus(s);
      setAgents(a);
      setFeed(f);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = useMemo(() => {
    const floor = SEVERITY_ORDER.indexOf(minSeverity);
    return feed.filter((e) => SEVERITY_ORDER.indexOf(e.severity) >= floor);
  }, [feed, minSeverity]);

  // Re-observe after the data lands, and again when the filter changes the
  // number of nodes. motion.js skips anything it already holds.
  const root = useReveals<HTMLDivElement>([status, agents.length, visible.length]);

  const stamp = status ? `observed ${relativeAge(status.sessionsLive.observed_at, now)} ago` : 'loading';

  return (
    <div ref={root} className="status">
      <ViewHeader title="Status" stamp={stamp}>
        <div className="sev-filter" role="group" aria-label="Minimum severity">
          {SEVERITY_ORDER.map((s) => (
            <button
              key={s}
              type="button"
              className="btn t-colors"
              aria-pressed={minSeverity === s}
              data-active={minSeverity === s ? 'true' : 'false'}
              onClick={() => setMinSeverity(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </ViewHeader>

      {/* ── counters ─────────────────────────────────────────────────────── */}
      <div className="stat-row" data-stagger>
        <Counter
          label="Live panes"
          reading={status?.sessionsLive}
          tone="accent"
          now={now}
        />
        <Counter label="In progress" reading={status?.tasksInProgress} tone="default" now={now} />
        <Counter label="Blocked" reading={status?.tasksBlocked} tone="bad" now={now} />
        <Counter label="Queue depth" reading={status?.queueDepth} tone="default" now={now} />
        <Counter label="Faults, 1h" reading={status?.faultsLastHour} tone="warn" now={now} />
      </div>

      {/* ── liveness ─────────────────────────────────────────────────────── */}
      <Card label="Agents" className="agents-card" reveal="up">
        <div className="chip-row" data-stagger>
          {agents.map((agent) => (
            <LiveChip
              key={agent.name}
              name={agent.name}
              live={agentLiveness(agent, now)}
              detail={agent.task ?? 'no task'}
              observedAt={agent.observed_at}
              onSelect={() =>
                blade.open({
                  kind: 'agent',
                  title: agent.name,
                  rows: [
                    { label: 'state', value: agent.state },
                    { label: 'liveness', value: agentLiveness(agent, now) },
                    { label: 'task', value: agent.task ?? '—' },
                    { label: 'pane', value: agent.cols && agent.rows ? `${agent.cols}x${agent.rows}` : '—' },
                    { label: 'uptime', value: uptime(agent.uptime_seconds) },
                    { label: 'observed', value: `${clock(agent.observed_at)} (${relativeAge(agent.observed_at, now)} ago)` },
                  ],
                  body:
                    agentLiveness(agent, now) === 'unknown'
                      ? `The last observation of this pane is older than the ${Math.round(STALE_AFTER_MS / 1000)}s staleness budget. That is not a statement that it stopped - it is a statement that nobody has checked recently.`
                      : undefined,
                })
              }
            />
          ))}
          {agents.length === 0 ? <p className="empty">No panes reported.</p> : null}
        </div>
        <p className="hint">
          A chip pulses only when liveness was measured: the session exists and the
          observation behind that claim is younger than {Math.round(STALE_AFTER_MS / 1000)}s. An
          older observation reads <em>unknown</em> rather than <em>dead</em> &mdash; we could not
          tell, and that is not a shade of bad.
        </p>
      </Card>

      {/* ── feed ─────────────────────────────────────────────────────────── */}
      <Card label={`Feed — ${visible.length} of ${feed.length}`} reveal="up">
        <ol className="feed" role="log" aria-live="polite">
          {visible.map((entry, i) => (
            <li
              key={`${entry.at}-${i}`}
              className="feed-row t-colors"
              data-severity={entry.severity}
            >
              <SeverityDot severity={entry.severity} />
              <Value value={clock(entry.at)} size="sm" tone="unknown" />
              <span className="feed-source">{entry.source}</span>
              <span className="feed-who">{entry.who}</span>
              {/* Text as text. Every one of these strings came from an agent,
                  a device or a tracker - none of it is markup we authored. */}
              <span className="feed-text">{entry.text}</span>
              <span className="feed-age">{relativeAge(entry.at, now)}</span>
            </li>
          ))}
          {visible.length === 0 ? (
            <li className="empty">Nothing at this severity or above.</li>
          ) : null}
        </ol>
      </Card>

      <Card label="Board, at a glance" reveal="up">
        <div className="glance">
          {(['in_progress', 'blocked', 'parked', 'done'] as const).map((s) => (
            <span key={s} className="glance-item">
              <StatusPill status={s} />
            </span>
          ))}
        </div>
        <p className="hint">
          The same six-status vocabulary the store uses. <em>parked</em> is a decision and
          is coloured as one; it is not a failure.
        </p>
      </Card>
    </div>
  );
}

/* One counter. The reading is a <Value>, so it swaps in a single frame; the
 * CARD around it is what reveals and what may flash. */
function Counter({
  label,
  reading,
  tone,
  now,
}: {
  label: string;
  reading: { value: number; unit?: string; observed_at: string } | undefined;
  tone: 'default' | 'accent' | 'warn' | 'bad';
  now: number;
}) {
  const live = reading ? readingLiveness(reading.observed_at, now) : 'unknown';

  return (
    <section className="stat" data-reveal="up" data-live={live}>
      <h3 className="stat-label">{label}</h3>
      {reading ? (
        <Value value={reading.value} unit={reading.unit} tone={tone} size="xl" flashOnChange />
      ) : (
        /* No reading yet is rendered as an em dash, not as 0. A zero is a
           measurement; "we have not asked yet" is not. */
        <Value value={'—'} tone="unknown" size="xl" />
      )}
      <span className="stat-age">
        {reading ? `${relativeAge(reading.observed_at, now)} ago` : 'not yet observed'}
      </span>
    </section>
  );
}
