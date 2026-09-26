import { useCallback, useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { BLADE_BOUNDS, useBlade } from './blade-state';
import { IconClose, IconFloat, IconPin } from './icons';

/* The blade. One element, three states, and it is never unmounted.
 *
 * NOT UNMOUNTED IS A FEATURE. Switching views swaps what is inside <main>; it
 * does not touch this element. So a console transcript, a scroll position or a
 * half-typed note survives navigation — which is the difference between a panel
 * people use and one they stop opening because it forgets.
 *
 * NO CSS TRANSFORM, EVER. The vanilla implementation records that a transform
 * resamples terminal glyphs into mush, so the panel animates its grid column
 * width instead. When Terminals moves into this app it will re-fit on
 * transitionend rather than per frame; four earlier attempts at per-frame
 * fitting oscillated, because a measurement taken at the current size fed the
 * choice of the next size.
 *
 * CONFIRMATIONS ARE CARDS, NEVER DIALOGS. Anything that writes to equipment or
 * to a tracker renders here, with the dry run visible, and you can leave it
 * open while you go and check something at the machine. A browser confirm()
 * blocks the page, cannot render a dry run, and cannot be left open — which is
 * why the lint config bans it outright rather than discouraging it.
 */

export function Blade() {
  const blade = useBlade();
  const dragging = useRef(false);
  const panel = useRef<HTMLElement>(null);

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      // Distance from the right edge of the window. Computed from clientX
      // rather than from a delta, so a dropped pointer event cannot accumulate
      // drift over a long drag.
      blade.setWidth(window.innerWidth - e.clientX);
    },
    [blade],
  );

  const onPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }, []);

  /* Keyboard resize. A drag handle that only accepts a pointer is a control
   * that does not exist for a keyboard user, and this one changes the layout. */
  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      const step = e.shiftKey ? 48 : 16;
      if (e.key === 'ArrowLeft') { e.preventDefault(); blade.setWidth(blade.width + step); }
      if (e.key === 'ArrowRight') { e.preventDefault(); blade.setWidth(blade.width - step); }
      if (e.key === 'Home') { e.preventDefault(); blade.setWidth(BLADE_BOUNDS.DEFAULT_W); }
    },
    [blade],
  );

  /* Focus moves into the blade when it opens as an OVERLAY only. In pinned it
   * is part of the layout and stealing focus would yank the caret out of
   * whatever the person was typing in the main region. */
  useEffect(() => {
    if (blade.state === 'overlay') panel.current?.focus();
  }, [blade.state, blade.subject]);

  const hidden = blade.state === 'hidden';
  const subject = blade.subject;

  return (
    <>
      {/* The backdrop exists only in overlay, and it is a sibling rather than a
          parent so that pinned never pays for it. Clicking it closes — the same
          affordance as Escape, which is deliberately overlay-only. */}
      {blade.state === 'overlay' ? (
        <div className="blade-backdrop t-opacity" onClick={blade.close} aria-hidden="true" />
      ) : null}

      <aside
        ref={panel}
        id="blade"
        className="blade"
        data-state={blade.state}
        role="complementary"
        aria-label="Detail panel"
        aria-hidden={hidden}
        tabIndex={-1}
        inert={hidden ? true : undefined}
      >
        <div
          className="blade-resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the panel"
          aria-valuenow={blade.width}
          aria-valuemin={BLADE_BOUNDS.MIN_W}
          aria-valuemax={BLADE_BOUNDS.MAX_W}
          tabIndex={hidden ? -1 : 0}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onKeyDown={onKeyDown}
        />

        <header className="blade-head">
          <span className="blade-title">{subject ? subject.title : 'Detail'}</span>
          <span className="blade-kind">{subject ? subject.kind : ''}</span>
          <span className="blade-spacer" />
          <button
            type="button"
            className="icon-btn t-colors pressable"
            onClick={blade.swapMode}
            title={
              blade.state === 'pinned'
                ? 'Float the panel over the view'
                : 'Pin the panel so the view reflows beside it'
            }
            aria-label={blade.state === 'pinned' ? 'Float the panel' : 'Pin the panel'}
          >
            {blade.state === 'pinned' ? <IconFloat /> : <IconPin />}
          </button>
          <button
            type="button"
            className="icon-btn t-colors pressable"
            onClick={blade.close}
            title="Hide the panel (Ctrl+`)"
            aria-label="Hide the panel"
          >
            <IconClose />
          </button>
        </header>

        <div className="blade-body">
          {subject ? (
            <>
              <dl className="blade-rows">
                {subject.rows.map((row) => (
                  <div className="blade-row" key={row.label}>
                    <dt>{row.label}</dt>
                    {/* Text, as text. Every string here came from an agent, a
                        tracker or a device, and none of them is trusted markup. */}
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
              {subject.body ? <p className="blade-note">{subject.body}</p> : null}
            </>
          ) : (
            <p className="blade-empty">
              Select a task, an epic or an agent to see its detail here. Pinned reflows the
              view beside it; floating covers it. Ctrl+` toggles, Ctrl+Shift+` swaps.
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
