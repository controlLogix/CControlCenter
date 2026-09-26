/* Formatting for things that are read at a glance on a dense screen.
 *
 * Every function here is a PURE STRING TRANSFORM, and that is the constraint
 * that matters: none of them rounds a value into being wrong. relativeAge()
 * floors rather than rounds, because "2m ago" for something 119 seconds old is
 * true and "2m ago" for something 90 seconds old is a claim the data did not
 * make.
 */

/** HH:MM:SS in the viewer's own zone. The API sends UTC; the operator is not in it. */
export function clock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--:--';
  return d.toLocaleTimeString(undefined, { hour12: false });
}

/**
 * "4s", "2m", "3h", "5d" - floored, never rounded up.
 *
 * Returns '?' rather than a guess when the timestamp will not parse. A feed row
 * with an unreadable timestamp is a row whose age is unknown, and the honest
 * rendering of an unknown age is not "0s".
 */
export function relativeAge(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '?';
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86_400)}d`;
}

/** Seconds as h/m, for an uptime column. Null in, em dash out - never "0m". */
export function uptime(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** in_progress -> "in progress". The store's vocabulary, made readable. */
export function humanStatus(status: string): string {
  return status.replace(/_/g, ' ');
}
