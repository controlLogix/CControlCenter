/* ─────────────────────────────────────────────────────────────────────────────
 * THIS IS MOCK DATA. NOTHING HERE CAME FROM A RUNNING SYSTEM.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * The Node API in packages/api is being built in parallel and is not ready, so
 * this module stands in for it. It is ONE module on purpose: when the API
 * lands, every fake in this app is in one file, and swapping it is a diff
 * against this file rather than a hunt through the views.
 *
 * WHERE THE REAL DATA WILL COME FROM. The vanilla dashboard already serves all
 * of this from the Python sidecar on 127.0.0.1:8787, and the Node API is
 * replacing that surface endpoint for endpoint. The mapping is exact:
 *
 *   fetchFeed()    -> GET /api/feed?limit=            (server.py feed_snapshot)
 *   fetchBoard()   -> GET /api/epics                  (ccstore.read(db,'epics'))
 *   fetchAgents()  -> GET /api/agents                 (server.py agents_snapshot)
 *   fetchStatus()  -> GET /api/status
 *
 * The TYPES below are not invented either - they are the shapes those endpoints
 * already return, including the vocabularies:
 *   FEED_SOURCES     dashboard/ccstore.py:510
 *   FEED_SEVERITIES  dashboard/ccstore.py:511
 *   STATUSES         dashboard/ccboard.py:55
 *   agent state      dashboard/server.py:1055-1057  (attached|detached|stale)
 * So the views are typed against the real contract today, and only the
 * transport is fake.
 *
 * ONE THING HERE IS NOT FAKE, AND IT MATTERS. Every timestamp is generated
 * relative to module load rather than hard-coded. A frozen timestamp would make
 * every age on screen grow without bound while the app is open, and an age is
 * the single value this product is most careful about being honest with. The
 * freshness logic in lib/freshness.ts then computes liveness from those
 * timestamps for real - so the observation is mock, but the JUDGEMENT about
 * whether an observation is fresh enough to claim "live" is the production one,
 * and it is what gates the pulse in motion.css.
 */

// ── vocabularies ────────────────────────────────────────────────────────────

export const FEED_SOURCES = ['chatter', 'journal', 'agent', 'provider', 'fault', 'run'] as const;
export type FeedSource = (typeof FEED_SOURCES)[number];

export const FEED_SEVERITIES = ['info', 'warn', 'error'] as const;
export type FeedSeverity = (typeof FEED_SEVERITIES)[number];

/** ccboard.py:55, minus 'deleted' - a deleted row is not on the board. */
export const BOARD_STATUSES = ['backlog', 'open', 'in_progress', 'blocked', 'parked', 'done'] as const;
export type BoardStatus = (typeof BOARD_STATUSES)[number];

export const AGENT_STATES = ['attached', 'detached', 'stale'] as const;
export type AgentState = (typeof AGENT_STATES)[number];

// ── shapes ──────────────────────────────────────────────────────────────────

export interface FeedEntry {
  /** UTC ISO-8601, normalised server-side. Never a client clock. */
  at: string;
  source: FeedSource;
  severity: FeedSeverity;
  who: string;
  text: string;
  ref: string;
}

export interface Task {
  id: number;
  epic_id: number;
  title: string;
  status: BoardStatus;
  agent: string | null;
  jira_key: string | null;
  updated_at: string;
}

export interface Epic {
  id: number;
  key: string;
  title: string;
  status: BoardStatus;
  jira_key: string | null;
  notes: string | null;
  updated_at: string;
  tasks: Task[];
}

export interface Agent {
  name: string;
  state: AgentState;
  /** The task key this pane is bound to, if any. */
  task: string | null;
  cols: number | null;
  rows: number | null;
  uptime_seconds: number | null;
  /** When this row was OBSERVED, not when it was rendered. Liveness reads this. */
  observed_at: string;
}

/**
 * A single reading, with the instant it was taken.
 *
 * `observed_at` is not decoration. A number with no age is a number you cannot
 * act on: 3 running agents observed four seconds ago and 3 running agents
 * observed at 09:15 this morning are different facts, and only one of them is
 * worth a decision. Every counter on the Status view carries one.
 */
export interface Reading {
  value: number;
  unit?: string;
  observed_at: string;
}

export interface StatusSnapshot {
  sessionsLive: Reading;
  tasksInProgress: Reading;
  tasksBlocked: Reading;
  queueDepth: Reading;
  faultsLastHour: Reading;
}

// ── the fixture clock ───────────────────────────────────────────────────────

const LOADED_AT = Date.now();

/** An ISO timestamp `seconds` in the past, measured from module load. */
function ago(seconds: number): string {
  return new Date(LOADED_AT - seconds * 1000).toISOString();
}

// ── the fixtures ────────────────────────────────────────────────────────────

const FEED: readonly FeedEntry[] = [
  { at: ago(6), source: 'agent', severity: 'info', who: 'claude', text: 'pane attached, 204x52', ref: 'state' },
  { at: ago(19), source: 'run', severity: 'info', who: 'codex', text: 'TM-118 started - packages/api scaffold', ref: 'TM-118' },
  { at: ago(34), source: 'chatter', severity: 'info', who: 'orchestrator', text: '-> codex: take the store first, the routes will not settle until the schema does', ref: 'plan' },
  { at: ago(58), source: 'journal', severity: 'warn', who: 'dashboard', text: 'modbus_rtu degraded - pyserial not importable, one panel disabled', ref: 'degraded' },
  { at: ago(96), source: 'provider', severity: 'info', who: 'resources', text: 'probe swept 7 resources in 812ms', ref: 'probe' },
  { at: ago(141), source: 'run', severity: 'error', who: 'grok', text: 'TM-114 review failed - two mutating endpoints missing the Origin guard', ref: 'TM-114' },
  { at: ago(203), source: 'chatter', severity: 'info', who: 'codex', text: '-> orchestrator: schema is in, WAL on, foreign_keys on', ref: 'reply' },
  { at: ago(288), source: 'agent', severity: 'info', who: 'grok', text: 'pane detached, session still alive', ref: 'state' },
  { at: ago(357), source: 'fault', severity: 'error', who: 'netscan', text: 'segment sweep returned no answer on 10.12.4.0/24 - this is not a statement that the segment is empty', ref: 'unknown' },
  { at: ago(441), source: 'journal', severity: 'info', who: 'dashboard', text: 'cc.db opened, user_version 4', ref: 'boot' },
  { at: ago(602), source: 'run', severity: 'info', who: 'claude', text: 'TM-121 done - blade state persisted per browser', ref: 'TM-121' },
  { at: ago(744), source: 'provider', severity: 'warn', who: 'resources', text: 'gateway probe timed out after 4s - outcome unknown, not retried', ref: 'unknown' },
  { at: ago(910), source: 'chatter', severity: 'info', who: 'orchestrator', text: '-> claude: the rail is eight views, not seven - runs landed after the spec', ref: 'plan' },
  { at: ago(1180), source: 'journal', severity: 'info', who: 'dashboard', text: 'theme set to cc-dark', ref: 'settings' },
];

const AGENTS: readonly Agent[] = [
  { name: 'claude', state: 'attached', task: 'TM-121', cols: 204, rows: 52, uptime_seconds: 8_412, observed_at: ago(4) },
  { name: 'codex', state: 'attached', task: 'TM-118', cols: 160, rows: 48, uptime_seconds: 6_050, observed_at: ago(4) },
  { name: 'grok', state: 'detached', task: 'TM-114', cols: 120, rows: 40, uptime_seconds: 3_311, observed_at: ago(5) },
  // Stale: the metadata file is on disk but tmux has no session by that name.
  // This row is the reason liveness is measured rather than assumed - it looks
  // exactly like the others until you read observed_at and state together.
  { name: 'scribe', state: 'stale', task: null, cols: null, rows: null, uptime_seconds: null, observed_at: ago(4_900) },
];

const EPICS: readonly Epic[] = [
  {
    id: 1,
    key: 'EP-001',
    title: 'React app shell',
    status: 'in_progress',
    jira_key: null,
    notes: 'Shell plus two signature views. The other six stay vanilla until this one is proven.',
    updated_at: ago(120),
    tasks: [
      { id: 11, epic_id: 1, title: 'Vite + React 19 + TanStack Router scaffold', status: 'done', agent: 'claude', jira_key: null, updated_at: ago(900) },
      { id: 12, epic_id: 1, title: 'Grid shell: rail | main | blade', status: 'in_progress', agent: 'claude', jira_key: null, updated_at: ago(120) },
      { id: 13, epic_id: 1, title: 'Blade: hidden / overlay / pinned, pinned reflows', status: 'in_progress', agent: 'claude', jira_key: null, updated_at: ago(180) },
      { id: 14, epic_id: 1, title: 'Status view on real reveal + stagger', status: 'open', agent: null, jira_key: null, updated_at: ago(2_400) },
      { id: 15, epic_id: 1, title: 'Port Terminals - blocked on the xterm fit measurement', status: 'blocked', agent: null, jira_key: null, updated_at: ago(5_100) },
    ],
  },
  {
    id: 2,
    key: 'EP-002',
    title: 'Node API',
    status: 'in_progress',
    jira_key: 'AM-204',
    notes: 'Replaces the Python sidecar surface endpoint for endpoint. Same guards on every mutating route.',
    updated_at: ago(19),
    tasks: [
      { id: 21, epic_id: 2, title: 'SQLite store, WAL, connection per request', status: 'done', agent: 'codex', jira_key: 'AM-205', updated_at: ago(1_500) },
      { id: 22, epic_id: 2, title: 'GET /api/feed - merge journal, queue, agents, probes', status: 'in_progress', agent: 'codex', jira_key: 'AM-206', updated_at: ago(19) },
      { id: 23, epic_id: 2, title: 'GET /api/epics with tasks nested', status: 'open', agent: null, jira_key: 'AM-207', updated_at: ago(3_000) },
      { id: 24, epic_id: 2, title: 'Session auth before the bind widens past 127.0.0.1', status: 'backlog', agent: null, jira_key: 'AM-208', updated_at: ago(9_000) },
    ],
  },
  {
    id: 3,
    key: 'EP-003',
    title: 'Design system',
    status: 'done',
    jira_key: null,
    notes: 'tokens.css, motion.css, motion.js, field.js. Framework-agnostic so the two frontends cannot drift.',
    updated_at: ago(2_100),
    tasks: [
      { id: 31, epic_id: 3, title: 'Token file: surfaces, accent ramp, motion, layout', status: 'done', agent: 'claude', jira_key: null, updated_at: ago(2_400) },
      { id: 32, epic_id: 3, title: 'Motion vocabulary with the value and liveness guards', status: 'done', agent: 'claude', jira_key: null, updated_at: ago(2_200) },
      { id: 33, epic_id: 3, title: 'WebGL field, half-rate, half-resolution, silent on failure', status: 'done', agent: 'claude', jira_key: null, updated_at: ago(2_100) },
    ],
  },
  {
    id: 4,
    key: 'EP-004',
    title: 'Security review',
    status: 'blocked',
    jira_key: 'AM-210',
    notes: 'Blocked on EP-002: there is no point reviewing routes that are still being written.',
    updated_at: ago(141),
    tasks: [
      { id: 41, epic_id: 4, title: 'Origin guard on every mutating endpoint', status: 'blocked', agent: 'grok', jira_key: 'AM-211', updated_at: ago(141) },
      { id: 42, epic_id: 4, title: 'Bounded body + 415 on missing JSON content type', status: 'parked', agent: null, jira_key: null, updated_at: ago(7_200) },
    ],
  },
];

// ── the seam ────────────────────────────────────────────────────────────────
//
// Async on purpose, even though every one of these returns immediately. The
// call sites are then already written the way they will be written against the
// real API, so swapping the body for a fetch() is a change here and nowhere
// else. Making them synchronous now would mean rewriting every view later, and
// a rewrite is where the loading and error states get forgotten.

export async function fetchFeed(limit = 200): Promise<FeedEntry[]> {
  return FEED.slice(0, limit).map((e) => ({ ...e }));
}

export async function fetchAgents(): Promise<Agent[]> {
  return AGENTS.map((a) => ({ ...a }));
}

export async function fetchBoard(): Promise<Epic[]> {
  return EPICS.map((e) => ({ ...e, tasks: e.tasks.map((t) => ({ ...t })) }));
}

export async function fetchStatus(): Promise<StatusSnapshot> {
  const live = AGENTS.filter((a) => a.state !== 'stale').length;
  const tasks = EPICS.flatMap((e) => e.tasks);
  return {
    sessionsLive: { value: live, unit: 'panes', observed_at: ago(4) },
    tasksInProgress: { value: tasks.filter((t) => t.status === 'in_progress').length, observed_at: ago(12) },
    tasksBlocked: { value: tasks.filter((t) => t.status === 'blocked').length, observed_at: ago(12) },
    queueDepth: { value: FEED.filter((e) => e.source === 'chatter').length, unit: 'msg', observed_at: ago(9) },
    faultsLastHour: { value: FEED.filter((e) => e.severity === 'error').length, observed_at: ago(9) },
  };
}
