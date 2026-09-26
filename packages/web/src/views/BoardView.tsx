import { useCallback, useEffect, useMemo, useState } from 'react';
import { useBlade } from '@/app/blade-state';
import { IconChevron } from '@/app/icons';
import { StatusPill, ViewHeader } from '@/components/ui';
import { Value } from '@/components/Value';
import { humanStatus, relativeAge } from '@/lib/format';
import { useReveals } from '@/motion/useReveals';
import { fetchBoard, type BoardStatus, type Epic, type Task } from '@/mock';
import './board.css';

/* Board — epics as collapsible cards, tasks as rows.
 *
 * THE COLLAPSE IS A CONTAINER TRANSITION, NOT A VALUE ONE. It animates
 * grid-template-rows between 0fr and 1fr, which is a height change on the card
 * - the counts and keys inside it swap in a single frame. See board.css.
 *
 * NOTHING HERE OPENS A BROWSER DIALOG. Selecting a task opens the blade with
 * its detail; when write actions land, the confirmation renders there as a card
 * with the dry run visible. A confirm() blocks the page, cannot show the dry
 * run, and cannot be left open while somebody walks over to the equipment to
 * check - which is why the lint config bans it as a rule rather than as a note.
 */

const OPEN_FIRST: readonly BoardStatus[] = ['in_progress', 'blocked'];

export function BoardView() {
  const blade = useBlade();
  const [epics, setEpics] = useState<Epic[]>([]);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchBoard().then((rows) => {
      if (cancelled) return;
      setEpics(rows);
      /* Open the epics that want somebody, collapsed for the rest. A board that
       * opens fully expanded makes the reader do the triage the board exists to
       * have already done. */
      setExpanded(new Set(rows.filter((e) => OPEN_FIRST.includes(e.status)).map((e) => e.id)));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const root = useReveals<HTMLDivElement>([epics.length]);

  const toggle = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const totals = useMemo(() => {
    const tasks = epics.flatMap((e) => e.tasks);
    const by = (s: BoardStatus) => tasks.filter((t) => t.status === s).length;
    return {
      tasks: tasks.length,
      in_progress: by('in_progress'),
      blocked: by('blocked'),
      done: by('done'),
    };
  }, [epics]);

  const openTask = useCallback(
    (epic: Epic, task: Task) => {
      blade.open({
        kind: 'task',
        title: task.title,
        rows: [
          { label: 'epic', value: `${epic.key} — ${epic.title}` },
          { label: 'status', value: humanStatus(task.status) },
          { label: 'agent', value: task.agent ?? 'unassigned' },
          { label: 'tracker', value: task.jira_key ?? 'not linked' },
          { label: 'updated', value: `${relativeAge(task.updated_at, now)} ago` },
        ],
        body:
          task.status === 'blocked'
            ? 'Blocked is a claim about something else. Open the blocker before re-planning this one.'
            : undefined,
      });
    },
    [blade, now],
  );

  return (
    <div ref={root} className="board">
      <ViewHeader title="Board" stamp={`${epics.length} epics`}>
        <div className="board-totals">
          <Total label="tasks" value={totals.tasks} tone="default" />
          <Total label="in progress" value={totals.in_progress} tone="accent" />
          <Total label="blocked" value={totals.blocked} tone="bad" />
          <Total label="done" value={totals.done} tone="ok" />
        </div>
        <button
          type="button"
          className="btn t-colors"
          onClick={() => setExpanded(new Set(epics.map((e) => e.id)))}
        >
          expand all
        </button>
        <button type="button" className="btn t-colors" onClick={() => setExpanded(new Set())}>
          collapse all
        </button>
      </ViewHeader>

      <div className="epic-grid" data-stagger>
        {epics.map((epic) => {
          const open = expanded.has(epic.id);
          const done = epic.tasks.filter((t) => t.status === 'done').length;

          return (
            <article
              key={epic.id}
              className="epic"
              data-reveal="up"
              data-open={open ? 'true' : 'false'}
              data-status={epic.status}
            >
              <h3 className="epic-head">
                <button
                  type="button"
                  className="epic-toggle t-colors"
                  aria-expanded={open}
                  aria-controls={`epic-body-${epic.id}`}
                  onClick={() => toggle(epic.id)}
                >
                  <IconChevron className="epic-chevron" />
                  <Value value={epic.key} size="sm" tone="unknown" className="epic-key" />
                  <span className="epic-title">{epic.title}</span>
                  <StatusPill status={epic.status} />
                  <Value
                    value={`${done}/${epic.tasks.length}`}
                    size="sm"
                    className="epic-count"
                    tone={done === epic.tasks.length ? 'ok' : 'default'}
                    title="Tasks done of tasks filed"
                  />
                </button>
              </h3>

              {/* The wrapper is what animates (0fr -> 1fr). The inner div must
                  carry overflow: hidden or the rows paint outside a collapsed
                  card. Both live in board.css. */}
              <div className="epic-collapse" id={`epic-body-${epic.id}`}>
                <div className="epic-collapse-inner">
                  <ul className="task-list">
                    {epic.tasks.map((task) => (
                      <li key={task.id}>
                        <button
                          type="button"
                          className="task t-colors"
                          data-status={task.status}
                          onClick={() => openTask(epic, task)}
                        >
                          <span className="task-bar" aria-hidden="true" />
                          <Value value={`#${task.id}`} size="sm" tone="unknown" />
                          <span className="task-title">{task.title}</span>
                          <span className="task-agent">{task.agent ?? '—'}</span>
                          <StatusPill status={task.status} />
                          <span className="task-age">{relativeAge(task.updated_at, now)}</span>
                        </button>
                      </li>
                    ))}
                    {epic.tasks.length === 0 ? (
                      <li className="empty">No tasks filed under this epic.</li>
                    ) : null}
                  </ul>

                  {epic.notes ? <p className="epic-notes">{epic.notes}</p> : null}

                  <footer className="epic-foot">
                    <span className="epic-meta">
                      {epic.jira_key ? `tracker ${epic.jira_key}` : 'not linked to a tracker'}
                    </span>
                    <span className="epic-meta">updated {relativeAge(epic.updated_at, now)} ago</span>
                  </footer>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {epics.length === 0 ? <p className="empty">The board is empty.</p> : null}
    </div>
  );
}

function Total({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'default' | 'accent' | 'ok' | 'bad';
}) {
  return (
    <span className="total">
      <Value value={value} tone={tone} size="md" />
      <span className="total-label">{label}</span>
    </span>
  );
}
