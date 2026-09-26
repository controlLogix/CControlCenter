/* Where every node goes — and it is arithmetic, not a simulation.
 *
 * WHY NOT A FORCE-DIRECTED GRAPH. Because a force layout is not reproducible,
 * and an operator who opens this view twice would see two different plants.
 * Worse, the distance between two nodes in a relaxed graph LOOKS like it means
 * something — proximity reads as relatedness — when it is really an artefact of
 * where the simulation happened to start. This product does not put shapes on
 * screen that imply facts nobody measured. So: a deterministic packing. Same
 * devices in, same coordinates out, on any machine, in any order.
 *
 * WHAT THE GEOMETRY MEANS, exactly and only:
 *
 *   a hub disc      one /24, as devicetree.py's tree() grouped it. Grouped by
 *                   subnet rather than by vendor or protocol because that is
 *                   how the person standing in front of the panel thinks about
 *                   it: this cabinet, that cell.
 *   a ring position an index within that subnet, sorted by address. It carries
 *                   NO other meaning. Nothing is closer to the hub for being
 *                   more important.
 *   a vertical stack ONE address whose sources disagreed. The twins sit exactly
 *                   above one another over a single footprint, because they are
 *                   one address, and the strut between them is the argument.
 *   a line to a hub the address arithmetic. It is NOT a cable and it is not a
 *                   claim that traffic flows along it. See adjacency below for
 *                   the only line in this scene that means a real link.
 *
 * Distances are in scene units and nothing converts them to metres. A 3D view
 * of a topology is not a floor plan, and pretending otherwise would be a
 * different kind of lie than the one this file avoids, but a lie all the same.
 */

import type {
  AdjacencyEdge,
  DeviceGroup,
  DeviceRow,
  DeviceTreeSnapshot,
  TopologyInput,
} from './types.ts';
import { splitDevice, type DeviceClaimNode } from './conflict.ts';
import { normalizeOrigin, specFor, type Origin } from './origin.ts';

export type Vec3 = readonly [number, number, number];

export interface LayoutOptions {
  /** Radius step between concentric rings inside one subnet. */
  ringStep: number;
  /** Height of the device plane above its hub disc. */
  deviceHeight: number;
  /** Vertical gap between the twins of one disagreeing address. */
  twinGap: number;
  /** Clear space between the outermost ring of one subnet and the next. */
  segmentGap: number;
  /** Floor for the subnet grid pitch, so two tiny subnets are not on top of each other. */
  minSegmentPitch: number;
}

export const DEFAULT_LAYOUT: Readonly<LayoutOptions> = Object.freeze({
  ringStep: 9,
  deviceHeight: 8,
  twinGap: 5.5,
  segmentGap: 16,
  minSegmentPitch: 36,
});

export interface SceneNode extends DeviceClaimNode {
  position: Vec3;
  /** The network this node's address was grouped into. */
  network: string;
  /** Shared by every twin of one address — the point the hub line lands on. */
  footprint: Vec3;
  /** Resolved from the origin. Colours are token NAMES; palette.ts resolves them. */
  wireframe: boolean;
  colorToken: string;
  opacity: number;
  halo: 'none' | 'accent';
  outline: 'solid' | 'dashed' | 'none';
  reading: string;
}

export interface SceneSegment {
  network: string;
  position: Vec3;
  radius: number;
  count: number;
  /** How many told us what they are, as opposed to merely having a port open. */
  selfReported: number;
}

export type LinkKind = 'segment' | 'conflict' | 'adjacency';

export interface SceneLink {
  kind: LinkKind;
  a: Vec3;
  b: Vec3;
  /** Only adjacency carries this: was the link observed, or inferred? */
  confidence?: 'observed' | 'inferred';
  origin?: Origin;
  /** Node or address ids, for hit-testing and for a selection panel. */
  from: string;
  to: string;
}

export interface SceneLayout {
  nodes: SceneNode[];
  segments: SceneSegment[];
  links: SceneLink[];
  bounds: { min: Vec3; max: Vec3; center: Vec3; radius: number };
  stats: {
    addresses: number;
    nodes: number;
    /** Addresses split because their sources disagreed. */
    conflicted: number;
    selfReported: number;
    segments: number;
    droppedAdjacency: number;
  };
}

const round = (n: number): number => Math.round(n * 1e4) / 1e4;

/* Numeric where the address is an IPv4, so .10 sorts after .9 — the same
 * ordering devicetree.py's _sort_key produces, so the ring order a person sees
 * here matches the row order they see in the 2D tree. */
function sortKey(address: string): [number, number, string] {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(address.trim());
  if (!m) return [1, 0, address];
  const octets = m.slice(1).map(Number);
  if (octets.some((o) => o > 255)) return [1, 0, address];
  return [0, ((octets[0] * 256 + octets[1]) * 256 + octets[2]) * 256 + octets[3], address];
}

function compareAddresses(a: string, b: string): number {
  const ka = sortKey(a);
  const kb = sortKey(b);
  if (ka[0] !== kb[0]) return ka[0] - kb[0];
  if (ka[1] !== kb[1]) return ka[1] - kb[1];
  return ka[2] < kb[2] ? -1 : ka[2] > kb[2] ? 1 : 0;
}

/* Only used when the caller hands over a bare array of rows. The grouped form
 * from /api/devices/tree is the normal path and its grouping is authoritative;
 * this is the same /24 rule restated so an ungrouped list still renders. */
function subnetOf(address: string): string {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(address.trim());
  if (!m) return 'unknown';
  const octets = m.slice(1).map(Number);
  if (octets.some((o) => o > 255)) return 'unknown';
  return `${octets[0]}.${octets[1]}.${octets[2]}.0/24`;
}

function isSelfReported(row: DeviceRow): boolean {
  const sources = Array.isArray(row.sources) ? row.sources : [];
  return sources.includes('cip-listidentity') || sources.includes('opcua-endpoints');
}

/** Accepts the snapshot or a bare row list, and always returns sorted groups. */
export function collectGroups(input: TopologyInput): DeviceGroup[] {
  if (!input) return [];

  let groups: DeviceGroup[];
  if (Array.isArray(input)) {
    const byNetwork = new Map<string, DeviceRow[]>();
    for (const row of input) {
      if (!row || typeof row !== 'object' || !row.address) continue;
      const network = subnetOf(String(row.address));
      const bucket = byNetwork.get(network);
      if (bucket) bucket.push(row);
      else byNetwork.set(network, [row]);
    }
    groups = [...byNetwork.entries()].map(([network, devices]) => ({
      network,
      devices,
      count: devices.length,
      self_reported: devices.filter(isSelfReported).length,
    }));
  } else {
    const raw = Array.isArray((input as DeviceTreeSnapshot).groups)
      ? (input as DeviceTreeSnapshot).groups
      : [];
    groups = raw
      .filter((g) => g && typeof g === 'object')
      .map((g) => ({
        network: String(g.network ?? 'unknown'),
        devices: (Array.isArray(g.devices) ? g.devices : []).filter(
          (d) => d && typeof d === 'object' && d.address,
        ),
        count: Number(g.count ?? 0),
        self_reported: Number(g.self_reported ?? 0),
      }));
  }

  // Sorted here, not trusted from the wire, so the layout is stable no matter
  // what order the caller assembled it in.
  for (const group of groups) {
    group.devices = [...group.devices].sort((a, b) =>
      compareAddresses(String(a.address), String(b.address)),
    );
  }
  return groups.sort((a, b) => (a.network < b.network ? -1 : a.network > b.network ? 1 : 0));
}

/* Concentric rings of 6, 12, 18 ... around the hub. Ring k holds 6k slots at
 * radius k, so the cumulative count through ring k is 3k(k+1). Odd rings are
 * phase-shifted by half a slot so the rings do not line up into spokes, which
 * would look like structure that is not there. */
function ringSlot(index: number): { ring: number; angle: number } {
  let k = 1;
  while (3 * k * (k + 1) <= index) k += 1;
  const start = 3 * (k - 1) * k;
  const capacity = 6 * k;
  const slot = index - start;
  const phase = k % 2 === 0 ? 0.5 : 0;
  return { ring: k, angle: (2 * Math.PI * (slot + phase)) / capacity };
}

function ringsNeeded(count: number): number {
  if (count <= 0) return 0;
  let k = 1;
  while (3 * k * (k + 1) < count) k += 1;
  return k;
}

function adjacencyOf(input: TopologyInput): AdjacencyEdge[] {
  if (!input || Array.isArray(input)) return [];
  const list = (input as DeviceTreeSnapshot).adjacency;
  return Array.isArray(list) ? list.filter((e) => e && typeof e === 'object') : [];
}

/**
 * Deterministic positions for every node, hub and line in the scene.
 *
 * Pure: no clock, no random, no DOM, no three.js. That is what lets the whole
 * spatial contract be tested in `node --test` with nothing mocked.
 */
export function layoutTopology(
  input: TopologyInput,
  options: Partial<LayoutOptions> = {},
): SceneLayout {
  const opt: LayoutOptions = { ...DEFAULT_LAYOUT, ...options };
  const groups = collectGroups(input);

  // One pitch for the whole grid, sized by the busiest subnet, so no two
  // subnets can overlap however lopsided the plant is.
  let maxRadius = 0;
  for (const group of groups) {
    maxRadius = Math.max(maxRadius, ringsNeeded(group.devices.length) * opt.ringStep);
  }
  const pitch = Math.max(opt.minSegmentPitch, 2 * maxRadius + opt.segmentGap);

  const cols = Math.max(1, Math.ceil(Math.sqrt(groups.length)));
  const rows = Math.max(1, Math.ceil(groups.length / cols));

  const nodes: SceneNode[] = [];
  const segments: SceneSegment[] = [];
  const links: SceneLink[] = [];
  const footprints = new Map<string, Vec3>();

  let addresses = 0;
  let conflicted = 0;
  let selfReported = 0;

  groups.forEach((group, gi) => {
    const col = gi % cols;
    const row = Math.floor(gi / cols);
    const hub: Vec3 = [
      round((col - (cols - 1) / 2) * pitch),
      0,
      round((row - (rows - 1) / 2) * pitch),
    ];
    const radius = ringsNeeded(group.devices.length) * opt.ringStep;

    segments.push({
      network: group.network,
      position: hub,
      radius: round(Math.max(radius, opt.ringStep * 0.6)),
      count: group.devices.length,
      selfReported: group.devices.filter(isSelfReported).length,
    });

    group.devices.forEach((device, di) => {
      const { ring, angle } = ringSlot(di);
      const r = ring * opt.ringStep;
      const footprint: Vec3 = [
        round(hub[0] + Math.cos(angle) * r),
        round(opt.deviceHeight),
        round(hub[2] + Math.sin(angle) * r),
      ];
      const address = String(device.address);
      footprints.set(address, footprint);
      addresses += 1;
      if (isSelfReported(device)) selfReported += 1;

      const claims = splitDevice(device);
      if (claims.length > 1) conflicted += 1;

      // The stack is centred on the footprint, so an unconflicted address and
      // the middle of a disagreement sit at the same height. Nothing is
      // promoted or demoted for having been argued about.
      const mid = (claims.length - 1) / 2;
      const placed: SceneNode[] = claims.map((claim, ci) => {
        const spec = specFor(claim.origin);
        return {
          ...claim,
          network: group.network,
          footprint,
          position: [
            footprint[0],
            round(footprint[1] + (ci - mid) * opt.twinGap),
            footprint[2],
          ] as Vec3,
          wireframe: spec.wireframe,
          colorToken: spec.colorToken,
          opacity: spec.opacity,
          halo: spec.halo,
          outline: spec.outline,
          reading: spec.reading,
        };
      });
      nodes.push(...placed);

      // One line per ADDRESS to its hub, never one per twin: a disagreement
      // about a vendor does not put a second device on the subnet.
      links.push({
        kind: 'segment',
        a: hub,
        b: footprint,
        from: group.network,
        to: address,
      });

      // The argument itself, drawn as the strut between the twins.
      for (let i = 0; i + 1 < placed.length; i += 1) {
        links.push({
          kind: 'conflict',
          a: placed[i].position,
          b: placed[i + 1].position,
          from: placed[i].id,
          to: placed[i + 1].id,
        });
      }
    });
  });

  // ── adjacency: the only lines here that claim a real link ─────────────────
  let droppedAdjacency = 0;
  for (const edge of adjacencyOf(input)) {
    const a = footprints.get(String(edge.a ?? ''));
    const b = footprints.get(String(edge.b ?? ''));
    const origin = normalizeOrigin(edge.source);
    // Dropped rather than drawn faintly. An edge nobody can be asked about is
    // not weak evidence of a cable; it is no evidence of one.
    if (!a || !b || origin === null) {
      droppedAdjacency += 1;
      continue;
    }
    const spec = specFor(origin);
    links.push({
      kind: 'adjacency',
      a,
      b,
      origin,
      confidence: spec.wireframe ? 'inferred' : 'observed',
      from: String(edge.a),
      to: String(edge.b),
    });
  }

  // ── bounds, for framing the camera ────────────────────────────────────────
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  const consider = (p: Vec3, pad = 0) => {
    minX = Math.min(minX, p[0] - pad); maxX = Math.max(maxX, p[0] + pad);
    minY = Math.min(minY, p[1]);       maxY = Math.max(maxY, p[1]);
    minZ = Math.min(minZ, p[2] - pad); maxZ = Math.max(maxZ, p[2] + pad);
  };
  for (const node of nodes) consider(node.position);
  for (const segment of segments) consider(segment.position, segment.radius);
  if (!Number.isFinite(minX)) {
    minX = minY = minZ = 0;
    maxX = maxY = maxZ = 0;
  }

  const center: Vec3 = [
    round((minX + maxX) / 2),
    round((minY + maxY) / 2),
    round((minZ + maxZ) / 2),
  ];
  const radius = round(
    Math.max(
      1,
      0.5 * Math.hypot(maxX - minX, maxY - minY, maxZ - minZ),
    ),
  );

  return {
    nodes,
    segments,
    links,
    bounds: {
      min: [round(minX), round(minY), round(minZ)],
      max: [round(maxX), round(maxY), round(maxZ)],
      center,
      radius,
    },
    stats: {
      addresses,
      nodes: nodes.length,
      conflicted,
      selfReported,
      segments: segments.length,
      droppedAdjacency,
    },
  };
}
