/* The shape this renderer consumes — which is the shape that already exists.
 *
 * This is `GET /api/devices/tree` verbatim: `dashboard/devicetree.py`'s
 * `tree(merge(...))`, the same JSON `dashboard/devicetree.js` already renders
 * in 2D. Nothing here is a new contract. A 3D view that needed its own device
 * shape would be a second inventory to keep in step with the first, and the
 * two would disagree on a Friday.
 *
 * The fields that matter most to this renderer are the ones a prettier data
 * model would have thrown away:
 *
 *   sources[]        WHICH kinds of knowing reported this address. A row that
 *                    is only `segment-scan` is an open port; a row that carries
 *                    `cip-listidentity` is a device that answered for itself.
 *   vendor_source    WHERE the vendor string came from, as free text, e.g.
 *                    "segment-scan (OUI)" or "cip-listidentity (the device
 *                    said so)". Never separated from `vendor`.
 *   conflicts[]      Two sources that disagreed, BOTH recorded. The merge
 *                    refuses to pick a winner; so does this renderer.
 *
 * These are declarations only — no runtime code lives in this file, so nothing
 * here can quietly normalise a field on the way past.
 */

/** One open port as `netscan.py` reports it. */
export interface DevicePort {
  port: number;
  service?: string | null;
  [extra: string]: unknown;
}

/** CIP ListIdentity's answer: the device's own account of itself. */
export interface DeviceIdentity {
  product_name?: string | null;
  product_code?: number | string | null;
  vendor?: string | null;
  device_type?: string | null;
  revision?: string | null;
  serial?: string | null;
  state?: string | number | null;
  status?: string | number | null;
}

/** One side of a disagreement: a value, and who said it. */
export interface ConflictValue {
  value: unknown;
  source: string | null;
}

/** A disagreement, recorded rather than resolved. */
export interface DeviceConflict {
  field: string;
  values: ConflictValue[];
}

/** The cc.db row an operator already saved. */
export interface PromotedDevice {
  id?: number | string | null;
  name?: string | null;
  kind?: string | null;
  port?: number | null;
  protocol?: string | null;
}

/** One merged row: one address, every source that reported it. */
export interface DeviceRow {
  address: string;
  sources: string[];
  hostname?: string | null;
  mac?: string | null;
  vendor?: string | null;
  vendor_source?: string | null;
  ports?: DevicePort[];
  identity?: DeviceIdentity | null;
  endpoints?: unknown[];
  promoted?: PromotedDevice | null;
  conflicts?: DeviceConflict[];
  suggested?: string[];
}

/** Rows grouped by the /24 they fall in — the cabinet, the cell. */
export interface DeviceGroup {
  network: string;
  devices: DeviceRow[];
  count: number;
  /** How many of these actually told us what they are. The point of the panel. */
  self_reported: number;
}

/* An OPTIONAL edge the caller may supply, and the only way a line between two
 * devices ever appears in this scene.
 *
 * The merge in devicetree.py produces no device-to-device adjacency: nothing
 * in a port sweep, a ListIdentity broadcast or an OPC UA endpoint list says
 * that box A is cabled to box B. So this renderer draws no such line unless
 * something that actually observed one hands it over, WITH the origin that
 * observed it. An edge whose `source` cannot be attributed is dropped rather
 * than drawn faintly, because a faint wrong cable is still a wrong cable. */
export interface AdjacencyEdge {
  a: string;
  b: string;
  /** Free text, normalised the same way `vendor_source` is. */
  source: string | null;
}

/** The whole snapshot, as `/api/devices/tree` returns it. */
export interface DeviceTreeSnapshot {
  groups: DeviceGroup[];
  total: number;
  conflicts: number;
  scan?: unknown;
  sources?: string[];
  /** Not produced by devicetree.py today. See AdjacencyEdge. */
  adjacency?: AdjacencyEdge[];
}

/** Either form `setData` accepts. A bare array is treated as ungrouped rows. */
export type TopologyInput = DeviceTreeSnapshot | DeviceRow[] | null | undefined;
