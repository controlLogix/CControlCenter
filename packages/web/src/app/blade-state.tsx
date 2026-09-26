import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

/* The blade's state, and the reason there are three of them.
 *
 * hidden | overlay | pinned — and PINNED IS NOT AN OVERLAY WITH A DIFFERENT
 * Z-INDEX. Pinned is a real grid column, so the main region NARROWS. That
 * distinction is the whole feature for the two things this console is for: a
 * terminal grid measures its own container to pick a font size, and a chart
 * measures its own container to pick a scale. A panel sitting on top of either
 * is useless — you cannot read what it covers, and the thing underneath has not
 * been told it got smaller. Overlay is the same panel taken out of flow, for a
 * glance that must not disturb a layout somebody arranged by hand.
 *
 * `last` remembers which of the two open states you were in, so closing and
 * reopening returns you to the one you chose rather than to a default.
 *
 * Persisted per browser, and a failure to persist is swallowed: losing a
 * remembered width is smaller than a page that will not boot in private mode.
 */

export type BladeState = 'hidden' | 'overlay' | 'pinned';

/** A blade payload. Untyped bodies are rendered as text, never as markup. */
export interface BladeSubject {
  kind: 'task' | 'epic' | 'agent' | 'feed';
  title: string;
  /** Label/value rows. Values are strings; nothing here is interpolated as HTML. */
  rows: Array<{ label: string; value: string }>;
  body?: string;
}

interface BladeApi {
  state: BladeState;
  width: number;
  subject: BladeSubject | null;
  open(subject?: BladeSubject): void;
  close(): void;
  toggle(): void;
  /** Swap pinned <-> overlay without closing. */
  swapMode(): void;
  setWidth(px: number): void;
}

const STORAGE_KEY = 'agentmux.web.blade.v1';

/* Bounds come from design/tokens.css (--blade-min / --blade-max). They are
 * repeated as numbers here ONLY because a pointer drag is arithmetic in JS and
 * cannot read a CSS length without a layout read per frame. They are lengths,
 * not colours or durations, and they are clamped in one place. */
const MIN_W = 320;
const MAX_W = 720;
const DEFAULT_W = 420;

const clampWidth = (n: number) => Math.min(MAX_W, Math.max(MIN_W, Math.round(n)));

interface Persisted {
  state: BladeState;
  width: number;
  last: 'overlay' | 'pinned';
}

function load(): Persisted {
  const fallback: Persisted = { state: 'hidden', width: DEFAULT_W, last: 'pinned' };
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
    if (!raw || typeof raw !== 'object') return fallback;
    const r = raw as Partial<Persisted>;
    return {
      state:
        r.state === 'pinned' || r.state === 'overlay' || r.state === 'hidden'
          ? r.state
          : fallback.state,
      width: Number.isFinite(r.width) ? clampWidth(Number(r.width)) : fallback.width,
      last: r.last === 'overlay' ? 'overlay' : 'pinned',
    };
  } catch {
    return fallback;
  }
}

const BladeContext = createContext<BladeApi | null>(null);

export function BladeProvider({ children }: { children: ReactNode }) {
  const [persisted, setPersisted] = useState<Persisted>(load);
  const [subject, setSubject] = useState<BladeSubject | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
    } catch {
      /* private mode: a remembered width is not worth a crash */
    }
  }, [persisted]);

  const open = useCallback((next?: BladeSubject) => {
    if (next) setSubject(next);
    setPersisted((p) => (p.state === 'hidden' ? { ...p, state: p.last } : p));
  }, []);

  const close = useCallback(() => {
    setPersisted((p) =>
      p.state === 'hidden' ? p : { ...p, state: 'hidden', last: p.state as 'overlay' | 'pinned' },
    );
  }, []);

  const toggle = useCallback(() => {
    setPersisted((p) =>
      p.state === 'hidden'
        ? { ...p, state: p.last }
        : { ...p, state: 'hidden', last: p.state as 'overlay' | 'pinned' },
    );
  }, []);

  const swapMode = useCallback(() => {
    setPersisted((p) => {
      if (p.state === 'hidden') return { ...p, state: p.last };
      const next = p.state === 'pinned' ? 'overlay' : 'pinned';
      return { ...p, state: next, last: next };
    });
  }, []);

  const setWidth = useCallback((px: number) => {
    setPersisted((p) => ({ ...p, width: clampWidth(px) }));
  }, []);

  /* Ctrl+`     toggles the blade
   * Ctrl+Shift+` swaps pinned and overlay
   * Escape     closes it, but ONLY in overlay. In pinned it is part of the
   *            layout, and Escape dismissing a column you deliberately docked
   *            is the behaviour that makes people stop docking things. */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '`') {
        e.preventDefault();
        if (e.shiftKey) swapMode();
        else toggle();
        return;
      }
      if (e.key === 'Escape' && persisted.state === 'overlay') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggle, swapMode, close, persisted.state]);

  const api = useMemo<BladeApi>(
    () => ({
      state: persisted.state,
      width: persisted.width,
      subject,
      open,
      close,
      toggle,
      swapMode,
      setWidth,
    }),
    [persisted.state, persisted.width, subject, open, close, toggle, swapMode, setWidth],
  );

  return <BladeContext.Provider value={api}>{children}</BladeContext.Provider>;
}

export function useBlade(): BladeApi {
  const api = useContext(BladeContext);
  if (!api) throw new Error('useBlade() outside <BladeProvider>');
  return api;
}

export const BLADE_BOUNDS = { MIN_W, MAX_W, DEFAULT_W };
