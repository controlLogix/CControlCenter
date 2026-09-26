/* Every colour, duration and font in this scene comes from design/tokens.css.
 *
 * THERE IS NOT ONE COLOUR VALUE IN THIS PACKAGE, and `palette.test.mjs` greps
 * the source tree to keep it that way. tokens.css says why in its own header:
 * a literal in a component is a value that cannot be changed centrally, and a
 * pile of them is how a design system stops being one. `design/field.js` has
 * the same rule for its shader — "a shader with its own hex literals is a
 * second source of truth for the palette, and it is the one nobody remembers
 * to update" — and this file is that file's readToken/hexToRgb, reused so the
 * two atmospheric layers cannot drift apart.
 *
 * THE FALLBACKS ARE GREY ON PURPOSE. When a token cannot be read — no DOM, a
 * stylesheet that has not loaded, a host that mounted this without tokens.css —
 * the honest answer is not "here is roughly what teal looks like". It is a
 * neutral. The scene stays completely readable in that state because the thing
 * that separates a confirmed device from a guessed one is the SURFACE, solid
 * versus wireframe, not the hue. Colour is the second channel here, never the
 * only one: a themed scene, an unthemed scene, a projector with a broken green
 * gun and an operator with a red-green colour vision deficiency all still
 * answer "do we know this, or did we guess it".
 *
 * DURATIONS ARE TOKENS TOO, and that is the reduced-motion contract. tokens.css
 * collapses every --dur-* to 0ms under prefers-reduced-motion, so a camera move
 * that reads its duration from --dur-slow becomes a jump with no branch in this
 * file at all. matchMedia is still checked separately, because tokens.css's
 * header is right that two guards are needed: one stops the work and one stops
 * the pixels, and either alone leaves the other half happening.
 */

export type Rgb = readonly [number, number, number];

/** Mid greys. Not a theme — the absence of one. See the header. */
const NEUTRAL: Rgb = Object.freeze([0.62, 0.62, 0.64]);
const NEUTRAL_DIM: Rgb = Object.freeze([0.36, 0.36, 0.38]);
const NEUTRAL_FAINT: Rgb = Object.freeze([0.2, 0.2, 0.22]);
const NEUTRAL_VOID: Rgb = Object.freeze([0.05, 0.05, 0.06]);
const NEUTRAL_BRIGHT: Rgb = Object.freeze([0.92, 0.93, 0.9]);

export interface TokenSource {
  /** Anything with documentElement + defaultView. Injected in tests. */
  documentElement?: unknown;
  defaultView?: unknown;
}

function hostDocument(doc?: unknown): any {
  if (doc) return doc;
  return typeof document === 'undefined' ? null : document;
}

function hostWindow(doc?: unknown): any {
  const d = hostDocument(doc);
  if (d && d.defaultView) return d.defaultView;
  return typeof window === 'undefined' ? null : window;
}

/** The raw declared text of a custom property, or '' if it cannot be read.
 * Never throws: a host without a DOM must get a silent empty string, not a
 * stack trace during a render. */
export function readToken(name: string, doc?: unknown): string {
  try {
    const d = hostDocument(doc);
    const w = hostWindow(doc);
    if (!d || !d.documentElement || !w || typeof w.getComputedStyle !== 'function') return '';
    const value = w.getComputedStyle(d.documentElement).getPropertyValue(name);
    return typeof value === 'string' ? value.trim() : '';
  } catch {
    return '';
  }
}

const HEX = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;
const RGB_FN = /^rgba?\(\s*([0-9.]+)[\s,]+([0-9.]+)[\s,]+([0-9.]+)/i;

/** Token text to linear-ish 0..1 triple. Returns the fallback on anything
 * unexpected, exactly as field.js does — a malformed token is not worth an
 * exception in a render loop. */
export function parseColor(text: string | null | undefined, fallback: Rgb = NEUTRAL): Rgb {
  const value = (text ?? '').trim();
  if (!value) return fallback;

  const hex = HEX.exec(value);
  if (hex) {
    let digits = hex[1];
    if (digits.length === 3) digits = digits.split('').map((c) => c + c).join('');
    const n = parseInt(digits, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }

  const fn = RGB_FN.exec(value);
  if (fn) {
    const nums = [Number(fn[1]), Number(fn[2]), Number(fn[3])];
    if (nums.every((n) => Number.isFinite(n))) {
      return [nums[0] / 255, nums[1] / 255, nums[2] / 255] as Rgb;
    }
  }
  return fallback;
}

/** Kept under field.js's name so the two files read as the same helper. */
export function hexToRgb(hex: string | null | undefined, fallback: Rgb = NEUTRAL): Rgb {
  return parseColor(hex, fallback);
}

export function readColor(name: string, fallback: Rgb = NEUTRAL, doc?: unknown): Rgb {
  return parseColor(readToken(name, doc), fallback);
}

/** 0xRRGGBB, computed from the triple — three.js wants a packed int and this
 * is the only place one is produced. It is arithmetic, not a literal. */
export function packRgb(rgb: Rgb): number {
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n * 255)));
  return (clamp(rgb[0]) << 16) | (clamp(rgb[1]) << 8) | clamp(rgb[2]);
}

/** '280ms' / '0.5s' / '0' -> milliseconds. Anything else returns the fallback.
 * This is how the reduced-motion block in tokens.css reaches the camera. */
export function readDurationMs(name: string, fallbackMs: number, doc?: unknown): number {
  const raw = readToken(name, doc);
  if (!raw) return fallbackMs;
  const m = /^(-?[0-9]*\.?[0-9]+)\s*(ms|s)?$/i.exec(raw);
  if (!m) return fallbackMs;
  const n = Number(m[1]);
  if (!Number.isFinite(n)) return fallbackMs;
  const ms = (m[2] ?? '').toLowerCase() === 's' ? n * 1000 : n;
  return Math.max(0, ms);
}

export function readNumberToken(name: string, fallback: number, doc?: unknown): number {
  const raw = readToken(name, doc);
  if (!raw) return fallback;
  const n = Number.parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}

/** Labels are drawn into a 2D canvas, so they need a font shorthand string. */
export function readFontStack(name: string, doc?: unknown): string {
  return readToken(name, doc) || 'monospace';
}

/* Reduced motion, asked two ways because the operator switch and the OS
 * setting are different facts and tokens.css honours both:
 *
 *   @media (prefers-reduced-motion: reduce)   the OS
 *   :root[data-motion="off"]                  an explicit switch, "independent
 *                                             of the OS setting. Someone
 *                                             running this on a plant floor
 *                                             machine may want it off without
 *                                             changing Windows." */
export function prefersReducedMotion(doc?: unknown): boolean {
  try {
    const d = hostDocument(doc);
    const w = hostWindow(doc);
    if (d?.documentElement?.dataset?.motion === 'off') return true;
    if (d?.documentElement?.getAttribute?.('data-motion') === 'off') return true;
    if (w && typeof w.matchMedia === 'function') {
      return Boolean(w.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }
  } catch {
    /* a host with no matchMedia is not a host that is telling us to animate */
  }
  return false;
}

export interface ScenePalette {
  /** Resolves any token name a TreatmentSpec asks for. */
  color(token: string, fallback?: Rgb): Rgb;
  packed(token: string, fallback?: Rgb): number;
  void_: Rgb;
  line: Rgb;
  lineStrong: Rgb;
  hub: Rgb;
  conflict: Rgb;
  label: Rgb;
  labelMuted: Rgb;
  selection: Rgb;
  fontMono: string;
  reducedMotion: boolean;
  focusMs: number;
  hoverMs: number;
}

/** Read once per build and once per theme change — never inside a frame. */
export function readPalette(doc?: unknown): ScenePalette {
  const color = (token: string, fallback: Rgb = NEUTRAL) => readColor(token, fallback, doc);
  return {
    color,
    packed: (token: string, fallback: Rgb = NEUTRAL) => packRgb(color(token, fallback)),
    void_: color('--surface-void', NEUTRAL_VOID),
    line: color('--line', NEUTRAL_FAINT),
    lineStrong: color('--line-strong', NEUTRAL_DIM),
    hub: color('--line-strong', NEUTRAL_DIM),
    // The one place the hot end of the accent ramp is used. tokens.css is
    // explicit that --accent-hot is "for a thing that needs a person NOW"; an
    // address whose sources contradict each other is exactly that, and it is
    // the only thing in this scene that gets it.
    conflict: color('--accent-hot', NEUTRAL),
    label: color('--text-primary', NEUTRAL_BRIGHT),
    labelMuted: color('--text-muted', NEUTRAL),
    selection: color('--accent', NEUTRAL),
    fontMono: readFontStack('--font-mono', doc),
    reducedMotion: prefersReducedMotion(doc),
    // Both collapse to 0 under the reduced-motion block in tokens.css.
    focusMs: readDurationMs('--dur-slow', 500, doc),
    hoverMs: readDurationMs('--dur-micro', 100, doc),
  };
}
