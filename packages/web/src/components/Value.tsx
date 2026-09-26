import { useEffect, useRef, type ReactNode } from 'react';
import './Value.css';

/* ─────────────────────────────────────────────────────────────────────────────
 * Value — every reading on screen goes through this, and it never animates.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * WHY THIS COMPONENT EXISTS, which is the only part of this file worth reading.
 *
 * The obvious polish for a dashboard number is to tween it: 41 rolls up to 47
 * over 300ms and the page feels alive. For the length of that tween the screen
 * displays 42, 43, 44, 45, 46 — and not one of those numbers was ever true. The
 * system never reported 44. On a marketing page that is a flourish. On a tag
 * table showing a live process value, a queue depth, a fault count or the
 * pressure in a vessel, it is a FALSE READING, rendered by the interface that
 * exists to tell the operator what is actually happening. An operator who
 * glances at the right moment reads a number that no instrument produced.
 *
 * It is not a polish detail with a caveat. It is the same failure as an
 * un-aged value or a port sweep reported as a statement: the UI asserting
 * something it does not know. This product's entire argument is that it does
 * not do that, so the fix is structural rather than advisory — the class that
 * opts out of all motion is applied by the component that renders the reading,
 * not by whoever remembers.
 *
 * `.is-value` is defined in design/motion.css as:
 *     .is-value, .is-value * { transition-property: none !important;
 *                              animation: none !important; }
 * It is deliberately aggressive, including over descendants, because a value
 * with a unit suffix or a sign prefix is still a value.
 *
 * WHAT MAY STILL MOVE. The container. A row is allowed to flash when its
 * reading changes — that draws the eye to a cell that has updated without ever
 * misstating what is in it. So the flash lives on the wrapper, OUTSIDE
 * `.is-value`, and the digits swap in a single frame inside it. That split is
 * the whole design: the container may transition, the value may not.
 *
 * Note also that the wrapper is what carries any tone colour and the flash, and
 * the inner span carries nothing but the text. Putting the animation inside
 * `.is-value` would be silently cancelled by the rule above — which is the
 * correct failure, but a confusing one to debug, so it is stated here.
 */

export type ValueTone = 'default' | 'accent' | 'ok' | 'warn' | 'bad' | 'unknown';
export type ValueSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ValueProps {
  /** The reading. A string is passed through untouched — no parsing, no rounding. */
  value: number | string;
  /** Rendered after the value, inside .is-value: a unit is part of the reading. */
  unit?: string;
  tone?: ValueTone;
  size?: ValueSize;
  /**
   * Flash the CONTAINER when `value` changes. Off by default: a screen where
   * everything flashes has told the operator nothing about where to look.
   */
  flashOnChange?: boolean;
  /** Extra classes for the wrapper. `.is-value` is not negotiable and is not here. */
  className?: string;
  title?: string;
  'aria-label'?: string;
  children?: ReactNode;
}

export function Value({
  value,
  unit,
  tone = 'default',
  size = 'md',
  flashOnChange = false,
  className,
  title,
  'aria-label': ariaLabel,
}: ValueProps) {
  const cell = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);

  useEffect(() => {
    if (!flashOnChange) return;
    if (previous.current === value) return;
    previous.current = value;

    const node = cell.current;
    if (!node) return;

    // Restart the animation on a second change inside its own duration:
    // removing the class and forcing a reflow is the only reliable way, and
    // without it a burst of updates flashes once and then looks frozen.
    node.classList.remove('value-flash');
    void node.offsetWidth;
    node.classList.add('value-flash');

    const done = () => node.classList.remove('value-flash');
    node.addEventListener('animationend', done, { once: true });
    return () => node.removeEventListener('animationend', done);
  }, [value, flashOnChange]);

  const wrapper = ['value-cell', `value-${tone}`, className].filter(Boolean).join(' ');

  return (
    <span ref={cell} className={wrapper} title={title}>
      {/* The className below is the invariant. Read the header before touching it. */}
      <span className={`is-value value-text value-${size}`} aria-label={ariaLabel}>
        {value}
        {unit ? <span className="value-unit">{unit}</span> : null}
      </span>
    </span>
  );
}
