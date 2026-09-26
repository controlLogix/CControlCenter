/* Origin → material. The whole argument of this view, in one table.
 *
 * `dashboard/devicetree.py` opens by saying it plainly: a TCP connect that
 * answered on port 44818 plus an OUI lookup is an INFERENCE; a device that
 * answered ListIdentity with its own vendor, product code, revision and serial
 * made a STATEMENT. Both are useful. They are not the same thing, and a screen
 * that renders them with the same confidence is worse than one that shows
 * less — because the operator cannot tell which half to trust, and eventually
 * stops trusting either.
 *
 * In 2D that difference is carried by a chip with a tooltip. In 3D a chip is
 * not available at a glance from an arbitrary camera angle, so it has to be
 * carried by the SURFACE: a device that spoke for itself is solid, a device we
 * merely inferred is a wireframe. You can read it from across the room, at any
 * rotation, with the labels off, with the colours wrong. That is the test the
 * treatment has to pass — colour alone would fail it under a retheme, a
 * projector, or a red-green colour vision deficiency.
 *
 * THE TABLE IS A WHITELIST, AND THE EXHAUSTIVENESS IS TESTED. Every origin maps
 * to exactly one treatment. `treatmentFor` throws on anything unlisted rather
 * than falling back to a default, because a default is how a new source ends up
 * rendered as though it were confirmed. If devicetree.py grows a fifth source,
 * `origin.test.mjs` fails until somebody decides here whether it is a statement
 * or a guess. That failure is the feature.
 */

/* The four the merge produces, in devicetree.py's own SOURCES order — which
 * that file describes as "how much the device itself told us, which is the
 * order a reader should trust them in. Used for display, never to pick a
 * winner." The same caveat applies here; see `effectiveOrigin` below.
 *
 * `unattributed` is the fifth and is NOT one of devicetree.py's. It is this
 * renderer's answer to a source string it cannot attribute — a row with an
 * empty `sources`, or a conflict value whose `source` matches nothing known.
 * It exists so that "we could not tell who said this" has a visual of its own
 * instead of being quietly folded into one of the four that mean something. */
export const UPSTREAM_SOURCES = Object.freeze([
  'promoted',
  'cip-listidentity',
  'opcua-endpoints',
  'segment-scan',
] as const);

export const ORIGINS = Object.freeze([
  ...UPSTREAM_SOURCES,
  'unattributed',
] as const);

export type Origin = (typeof ORIGINS)[number];

/** The three ways a surface can answer "do we know this, or did we guess it". */
export type Treatment = 'statement' | 'asserted' | 'inference' | 'unattributed';

/* The whitelist. One line per origin, no default branch, no fallthrough.
 *
 *   statement     The DEVICE said so. CIP ListIdentity and an OPC UA endpoint
 *                 list are both self-reported by the equipment.
 *   asserted      A PERSON said so. A promoted row is an operator's saved
 *                 record; it is a strong claim, but it is a human's claim about
 *                 the device, not the device's claim about itself, and the two
 *                 fail differently — a promoted row survives the device being
 *                 swapped for a different one at the same address.
 *   inference     WE guessed. A port answered and an OUI table named a vendor.
 *   unattributed  Nobody identifiable said anything. See above. */
export const TREATMENTS: Readonly<Record<Origin, Treatment>> = Object.freeze({
  'promoted': 'asserted',
  'cip-listidentity': 'statement',
  'opcua-endpoints': 'statement',
  'segment-scan': 'inference',
  'unattributed': 'unattributed',
});

/** What a treatment does to a surface. Colours are TOKEN NAMES, never values —
 * `palette.ts` resolves them at render time so retheming the product rethemes
 * the scene. Nothing in this package holds a colour of its own. */
export interface TreatmentSpec {
  /** The load-bearing bit. Solid means somebody said so; wireframe means we guessed. */
  wireframe: boolean;
  /** Token consulted for the body colour. */
  colorToken: string;
  /** 0..1. Only ever reduced for things we are less sure of. */
  opacity: number;
  /** A thin ring around the node, or none. Used to separate "a person said so". */
  halo: 'none' | 'accent';
  /** Dashed silhouettes read as provisional; solid ones read as settled. */
  outline: 'solid' | 'dashed' | 'none';
  /** Shown in a selection panel and a legend, and written to `data-treatment`. */
  reading: string;
}

export const TREATMENT_SPEC: Readonly<Record<Treatment, TreatmentSpec>> = Object.freeze({
  statement: Object.freeze({
    wireframe: false,
    colorToken: '--cool',
    opacity: 1,
    halo: 'none',
    outline: 'solid',
    reading: 'the device answered for itself',
  }),
  asserted: Object.freeze({
    wireframe: false,
    colorToken: '--accent-soft',
    opacity: 1,
    halo: 'accent',
    outline: 'solid',
    reading: 'an operator saved this one',
  }),
  inference: Object.freeze({
    wireframe: true,
    // --unknown is documented in tokens.css as deliberately colourless-ish:
    // "we could not tell" is not a shade of bad and must never read as one.
    // That is exactly what an open port with an OUI guess is.
    colorToken: '--unknown',
    opacity: 0.85,
    halo: 'none',
    outline: 'dashed',
    reading: 'a port answered; nothing identified itself',
  }),
  unattributed: Object.freeze({
    wireframe: true,
    colorToken: '--unknown',
    opacity: 0.45,
    halo: 'none',
    outline: 'dashed',
    reading: 'no source could be attributed to this claim',
  }),
});

const ORIGIN_SET: ReadonlySet<string> = new Set<string>(ORIGINS);

/** Longest first, so a future source that is a prefix of another cannot be
 * matched by the shorter one. None of the current four are, and that is luck
 * rather than design, so it is not relied on. */
const ORIGINS_BY_LENGTH: readonly string[] = [...ORIGINS].sort((a, b) => b.length - a.length);

export function isOrigin(value: unknown): value is Origin {
  return typeof value === 'string' && ORIGIN_SET.has(value);
}

/* Source strings arrive in two forms and both have to land on the same origin:
 *
 *   row.sources[]     bare, e.g. "cip-listidentity"
 *   row.vendor_source free text, e.g. "cip-listidentity (the device said so)"
 *                     or "segment-scan (OUI)"
 *
 * The parenthetical is prose for a human and is deliberately not parsed. What
 * is required is that the string BEGINS with a known source and the next
 * character is not a word character — so "segment-scanner" would not silently
 * become "segment-scan". Anything else returns null; the caller decides what
 * an unattributable source means, and in this package it means `unattributed`
 * rather than a guess. */
export function normalizeOrigin(source: string | null | undefined): Origin | null {
  if (typeof source !== 'string') return null;
  const text = source.trim().toLowerCase();
  if (!text) return null;
  for (const candidate of ORIGINS_BY_LENGTH) {
    if (text === candidate) return candidate as Origin;
    if (text.startsWith(candidate)) {
      const next = text.charAt(candidate.length);
      if (!/[a-z0-9_-]/.test(next)) return candidate as Origin;
    }
  }
  return null;
}

/** Same, but never null: an unrecognised source is `unattributed`, which has
 * its own treatment and is not mistaken for any of the four real ones. */
export function originOf(source: string | null | undefined): Origin {
  return normalizeOrigin(source) ?? 'unattributed';
}

/** Throws on an unclassified origin. No default branch, on purpose — see the
 * header. The thrown error names the origin so the fix is obvious. */
export function treatmentFor(origin: string): Treatment {
  const treatment = (TREATMENTS as Record<string, Treatment | undefined>)[origin];
  if (treatment === undefined) {
    throw new Error(
      `scene/origin: "${origin}" has no treatment. Every origin must be classified ` +
      `in TREATMENTS as a statement, an assertion, an inference or unattributed ` +
      `before it can be rendered — there is no default, because a default would ` +
      `draw a guess as though it were confirmed.`,
    );
  }
  return treatment;
}

export function specFor(origin: string): TreatmentSpec {
  return TREATMENT_SPEC[treatmentFor(origin)];
}

/* Rank, for choosing which of several CORROBORATING origins sets the surface.
 *
 * Read the caveat before using this anywhere else. devicetree.py says the
 * SOURCES order is "used for display, never to pick a winner", and it means it:
 * when two sources DISAGREE about a field, picking the higher-ranked one is the
 * exact failure this product exists to avoid. That case never reaches this
 * function — `conflict.ts` has already split the row into one node per
 * claimant, so each node here carries exactly one origin.
 *
 * What this resolves is the other case: a row whose sources AGREE, or do not
 * overlap at all. An address that was port-swept AND answered ListIdentity is
 * a device that spoke for itself; rendering it as a wireframe because a port
 * sweep also saw it would understate what is known. So the strongest kind of
 * knowing sets the surface, and every origin the row carries is kept on the
 * node and shown on selection. Nothing is discarded, only ranked. */
const ORIGIN_RANK: Readonly<Record<Origin, number>> = Object.freeze({
  'cip-listidentity': 0,
  'opcua-endpoints': 1,
  'promoted': 2,
  'segment-scan': 3,
  'unattributed': 4,
});

export function rankOf(origin: Origin): number {
  return ORIGIN_RANK[origin];
}

/** The strongest kind of knowing among a set of agreeing sources. Empty in,
 * `unattributed` out — a row with no sources is not a confirmed device. */
export function effectiveOrigin(sources: readonly (string | null | undefined)[]): Origin {
  let best: Origin = 'unattributed';
  let bestRank = Number.POSITIVE_INFINITY;
  for (const source of sources ?? []) {
    const origin = normalizeOrigin(source);
    if (origin === null) continue;
    const rank = ORIGIN_RANK[origin];
    if (rank < bestRank) {
      bestRank = rank;
      best = origin;
    }
  }
  return best;
}

/** Every distinct origin a row stands on, in trust order, duplicates removed.
 * Kept whole on the node so a selection panel can say "this was seen by a port
 * sweep AND answered ListIdentity" rather than only the stronger half. */
export function originsOf(sources: readonly (string | null | undefined)[]): Origin[] {
  const found = new Set<Origin>();
  for (const source of sources ?? []) {
    const origin = normalizeOrigin(source);
    if (origin !== null) found.add(origin);
  }
  return [...found].sort((a, b) => ORIGIN_RANK[a] - ORIGIN_RANK[b]);
}
