/* One address, two stories: how a disagreement becomes two nodes.
 *
 * `dashboard/devicetree.py` states the rule and enforces it in the merge:
 *
 *     DISAGREEMENT IS DATA, NOT AN ERROR TO RESOLVE. If the OUI table says one
 *     vendor and the device says another, both are recorded and the row is
 *     flagged. Picking a winner - newest, most specific, highest priority - is
 *     how the wrong one ends up on screen with nothing to say it was ever in
 *     doubt.
 *
 * A renderer can break that rule in a way the merge cannot: by drawing one box
 * and putting the disagreement in a tooltip. The box is what a person sees from
 * six feet away, and one box means one device with one vendor. So a conflicted
 * row is SPLIT here — one node per claimant — before it reaches the scene
 * graph. There is no code path in this package that produces a single node for
 * a row that carries a conflict, and `conflict.test.mjs` asserts it.
 *
 * WHAT A CLAIMANT IS. The literal `source` string on each recorded value, not
 * its normalised origin. Two claimants that happen to normalise to the same
 * origin are still two claimants and still get two nodes; collapsing them would
 * be the same averaging, one level down.
 *
 * WHAT ATTACHES TO NEITHER TWIN. A source that reported the ADDRESS but said
 * nothing about the disputed field — an OPC UA endpoint list, say, when the
 * argument is about vendor — is not a party to the argument. It is recorded on
 * every twin as `corroborating` and given no surface of its own, because giving
 * it one would invent a third opinion nobody holds.
 */

import type { DeviceRow, DeviceConflict } from './types.ts';
import {
  type Origin,
  type Treatment,
  effectiveOrigin,
  originOf,
  originsOf,
  treatmentFor,
} from './origin.ts';

/** One field a claimant asserted a value for. */
export interface Claim {
  field: string;
  value: unknown;
  /** The literal source text as devicetree.py recorded it. Never rewritten. */
  source: string | null;
  origin: Origin;
}

/** One node's worth of device: an address as ONE claimant tells it. */
export interface DeviceClaimNode {
  /** Stable across rebuilds for the same input. */
  id: string;
  address: string;
  /** Which of this address's nodes this is, and how many there are. */
  claimIndex: number;
  claimCount: number;
  /** True when this address was split because its sources disagreed. */
  conflicted: boolean;
  /** The origin whose confidence this node's surface expresses. */
  origin: Origin;
  treatment: Treatment;
  /** Everything this node stands on, strongest first. */
  origins: Origin[];
  /** Sources that reported the address but made no claim on a disputed field. */
  corroborating: Origin[];
  /** The disputed values this claimant asserted. Empty when unconflicted. */
  claims: Claim[];
  /** The literal claimant key; the free text a human should be shown. */
  claimant: string | null;
  label: string;
  sublabel: string;
  /** The merged row, untouched, so a panel can render what the 2D tree does. */
  device: DeviceRow;
}

/* devicetree.py writes at most one `vendor_source`-shaped free-text side and
 * one bare-source side per conflict, so the two sides are normally distinct
 * strings. Within a single conflict, an accidental repeat is disambiguated by
 * position rather than merged — two recorded values are two recorded values. */
function claimantKey(entrySource: string | null, seenInThisConflict: Set<string>): string {
  const base = (entrySource ?? '').trim() || '(source not recorded)';
  if (!seenInThisConflict.has(base)) {
    seenInThisConflict.add(base);
    return base;
  }
  let n = 2;
  while (seenInThisConflict.has(`${base} #${n}`)) n += 1;
  const key = `${base} #${n}`;
  seenInThisConflict.add(key);
  return key;
}

function conflictsOf(row: DeviceRow): DeviceConflict[] {
  const list = row.conflicts;
  return Array.isArray(list) ? list.filter((c) => c && typeof c === 'object') : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return 'not recorded';
  if (typeof value === 'string') return value;
  return String(value);
}

function unconflictedSublabel(row: DeviceRow): string {
  const identity = row.identity ?? {};
  const name = identity.product_name || row.hostname || row.promoted?.name;
  // The 2D panel's exact wording for the honest absence of a name: an address
  // nothing named is an open port, not a known device. Never a blank.
  return name ? String(name) : 'unidentified';
}

/**
 * Split one merged row into the nodes that should appear in the scene.
 *
 * Returns exactly one node when nothing disagreed, and NEVER one when
 * something did. The caller does not get to opt out of the split.
 */
export function splitDevice(row: DeviceRow): DeviceClaimNode[] {
  const address = String(row?.address ?? '').trim();
  if (!address) return [];

  const rowSources: string[] = Array.isArray(row.sources) ? row.sources : [];
  const conflicts = conflictsOf(row);

  if (conflicts.length === 0) {
    const origins = originsOf(rowSources);
    const origin = effectiveOrigin(rowSources);
    return [{
      id: address,
      address,
      claimIndex: 0,
      claimCount: 1,
      conflicted: false,
      origin,
      treatment: treatmentFor(origin),
      origins,
      corroborating: origins.filter((o) => o !== origin),
      claims: [],
      claimant: null,
      label: address,
      sublabel: unconflictedSublabel(row),
      device: row,
    }];
  }

  // ── the row is flagged: gather the parties to the argument ────────────────
  const byClaimant = new Map<string, Claim[]>();
  for (const conflict of conflicts) {
    const field = String(conflict.field ?? 'value');
    const values = Array.isArray(conflict.values) ? conflict.values : [];
    const seen = new Set<string>();
    for (const entry of values) {
      if (!entry || typeof entry !== 'object') continue;
      const key = claimantKey(entry.source ?? null, seen);
      const claim: Claim = {
        field,
        value: entry.value,
        source: entry.source ?? null,
        origin: originOf(entry.source),
      };
      const existing = byClaimant.get(key);
      if (existing) existing.push(claim);
      else byClaimant.set(key, [claim]);
    }
  }

  const keys = [...byClaimant.keys()];

  /* A flagged row with fewer than two recorded sides is malformed — the merge
   * does not produce it. If it ever arrives, the flag is still true and must
   * still be visible, so the missing side is drawn as an explicitly
   * unattributed node rather than dropped. That is not inventing a device: the
   * address is the same one, and the node says in as many words that the other
   * half of the disagreement was not recorded. It renders at the lowest
   * confidence this package has. */
  while (keys.length < 2) {
    keys.push(`(side ${keys.length + 1} of this disagreement was not recorded)`);
  }

  // Sources that reported the address but are not party to any dispute.
  const claimantOrigins = new Set<Origin>();
  for (const claims of byClaimant.values()) {
    for (const claim of claims) claimantOrigins.add(claim.origin);
  }
  const corroborating = originsOf(rowSources).filter((o) => !claimantOrigins.has(o));

  return keys.map((key, index) => {
    const claims = byClaimant.get(key) ?? [];
    const origin = claims.length ? claims[0].origin : 'unattributed';
    const first = claims[0];
    return {
      id: `${address}#${key}`,
      address,
      claimIndex: index,
      claimCount: keys.length,
      conflicted: true,
      origin,
      treatment: treatmentFor(origin),
      origins: [origin],
      corroborating,
      claims,
      claimant: claims.length ? (first.source ?? key) : key,
      label: address,
      // The twin says what it claims and who claimed it, so the two boxes over
      // one address are self-explaining without a click.
      sublabel: first
        ? `${first.field}: ${displayValue(first.value)}`
        : 'not recorded',
      device: row,
    };
  });
}

/** Every node for a list of rows, in input order. */
export function splitDevices(rows: readonly DeviceRow[]): DeviceClaimNode[] {
  const out: DeviceClaimNode[] = [];
  for (const row of rows ?? []) out.push(...splitDevice(row));
  return out;
}
