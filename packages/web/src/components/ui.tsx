import type { ReactNode } from 'react';
import type { Liveness } from '@/lib/freshness';
import type { BoardStatus } from '@/mock';
import { humanStatus, relativeAge } from '@/lib/format';
import './ui.css';

/* Small shared parts. Each one exists because the alternative was the same
 * markup written slightly differently in two views, and "slightly differently"
 * is how a design system turns back into a pile of one-offs. */

// ── Card ────────────────────────────────────────────────────────────────────

export interface CardProps {
  label?: string;
  children: ReactNode;
  /** Reveal direction for design/motion.css. Omit to opt the card out entirely. */
  reveal?: 'up' | 'down' | 'none' | 'scale';
  className?: string;
}

/** A panel: one hairline, near-black surface, 6px radius. No shadow — in this
 *  identity separation is a 1px border's job, and a shadow on a dense grid of
 *  cards reads as blur rather than as depth. */
export function Card({ label, children, reveal = 'up', className }: CardProps) {
  return (
    <section className={['card', className].filter(Boolean).join(' ')} data-reveal={reveal}>
      {label ? <h3 className="card-label">{label}</h3> : null}
      {children}
    </section>
  );
}

// ── LiveChip ────────────────────────────────────────────────────────────────

export interface LiveChipProps {
  name: string;
  /** MEASURED, by lib/freshness. Nothing else may pass 'true' here. */
  live: Liveness;
  detail?: string;
  /** The instant the observation behind `live` was taken. Always shown. */
  observedAt: string;
  onSelect?: () => void;
}

/**
 * A chip that may pulse — and only when liveness was measured.
 *
 * `data-live` is spelled out as the string the CSS gate expects, and it is set
 * from the `live` prop rather than derived here, because the moment this
 * component can compute its own liveness is the moment a decorative default
 * creeps in. motion.css animates `[data-live="true"].is-live-pulse` and nothing
 * else, so 'false' and 'unknown' render completely static — which is the whole
 * point: a dead feed must look dead.
 *
 * The age is rendered beside it in every state. A pulse says "now"; the age
 * says how long ago "now" was measured, and the second one is checkable.
 */
export function LiveChip({ name, live, detail, observedAt, onSelect }: LiveChipProps) {
  const label =
    live === 'true' ? 'live' : live === 'false' ? 'not running' : 'unknown';

  return (
    <button
      type="button"
      className={`chip is-live-pulse t-colors pressable chip-${live}`}
      data-live={live}
      onClick={onSelect}
      title={`${name} — ${label}, observed ${relativeAge(observedAt)} ago`}
    >
      <span className="chip-dot" aria-hidden="true" />
      <span className="chip-name">{name}</span>
      {detail ? <span className="chip-detail">{detail}</span> : null}
      <span className="chip-age">{relativeAge(observedAt)}</span>
    </button>
  );
}

// ── StatusPill ──────────────────────────────────────────────────────────────

/** The board's own vocabulary (ccboard.py:55), coloured by verdict not by mood.
 *  `blocked` gets --bad and `parked` gets --unknown: parked is a decision, not
 *  a failure, and colouring it red would make a tidy board look like a fire. */
export function StatusPill({ status }: { status: BoardStatus }) {
  return (
    <span className={`pill pill-${status}`} data-status={status}>
      {humanStatus(status)}
    </span>
  );
}

// ── SeverityDot ─────────────────────────────────────────────────────────────

export function SeverityDot({ severity }: { severity: 'info' | 'warn' | 'error' }) {
  return <span className={`sev sev-${severity}`} aria-label={severity} role="img" />;
}

// ── ViewHeader ──────────────────────────────────────────────────────────────

export function ViewHeader({
  title,
  stamp,
  children,
}: {
  title: string;
  stamp?: string;
  children?: ReactNode;
}) {
  return (
    <header className="vhead">
      <h2 className="vhead-title">{title}</h2>
      {stamp ? (
        <span className="vhead-stamp" aria-live="polite">
          {stamp}
        </span>
      ) : null}
      <span className="vhead-spacer" />
      {children}
    </header>
  );
}
