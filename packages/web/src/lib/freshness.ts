/* Liveness, measured. This is the module motion.css's pulse gate depends on.
 *
 * motion.css will only animate `[data-live="true"].is-live-pulse`, and the
 * comment there says why: "a decorative pulse that means live is a claim about
 * freshness made by CSS rather than by measurement". This file is the
 * measurement. Nothing else in the app is allowed to write data-live="true".
 *
 * THE RULE. A thing is live when BOTH hold:
 *   1. the source said it is currently running, and
 *   2. the observation that said so is younger than the staleness budget.
 *
 * Either alone is a lie in a different direction. (1) without (2) keeps a chip
 * pulsing off a snapshot taken before lunch. (2) without (1) says a session
 * that tmux has no record of is live because we asked recently.
 *
 * AND THE THIRD ANSWER. isLive() returns 'true' | 'false' | 'unknown', not a
 * boolean. A sidecar that did not answer has not told us the agent is dead - it
 * has told us nothing, and "we could not tell" is not a shade of dead. That is
 * why tokens.css gives --unknown its own deliberately colourless value instead
 * of letting it fall back to --bad.
 */

import type { Agent } from '@/mock';

/** How old an observation may be before it stops supporting a liveness claim.
 *  Chosen as a small multiple of the dashboard's own poll interval: anything
 *  older than a few polls means a poll was missed, and a missed poll is exactly
 *  the case where the last value is least trustworthy. */
export const STALE_AFTER_MS = 30_000;

export type Liveness = 'true' | 'false' | 'unknown';

export function ageMs(observedAt: string, now = Date.now()): number | null {
  const t = Date.parse(observedAt);
  return Number.isFinite(t) ? now - t : null;
}

/**
 * Liveness of a tmux-backed agent pane.
 *
 * 'attached' and 'detached' both mean the session exists - a detached session
 * is running, nobody is watching it. 'stale' means metadata on disk with no
 * session behind it, which is the one case that is genuinely not live.
 */
export function agentLiveness(agent: Agent, now = Date.now()): Liveness {
  const age = ageMs(agent.observed_at, now);
  if (age === null) return 'unknown';          // unparseable timestamp: say so
  if (age > STALE_AFTER_MS) return 'unknown';  // the value is old, not false
  return agent.state === 'stale' ? 'false' : 'true';
}

/** Liveness of a reading, for a counter chip. Same rule, no session to consult. */
export function readingLiveness(observedAt: string, now = Date.now()): Liveness {
  const age = ageMs(observedAt, now);
  if (age === null) return 'unknown';
  return age <= STALE_AFTER_MS ? 'true' : 'unknown';
}
