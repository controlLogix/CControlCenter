/* @agentmux/scene — a 3D view of the device tree that does not overstate it.
 *
 * One entry point that matters:
 *
 *     import { createTopology } from '@agentmux/scene';
 *
 *     const view = createTopology(el, {
 *       onSelect: (device) => showPanel(device),
 *       onUnavailable: () => showTheTwoDimensionalTree(),
 *     });
 *     if (!view.ok) showTheTwoDimensionalTree();
 *     view.setData(await (await fetch('/api/devices/tree')).json());
 *     // on unmount:
 *     view.dispose();
 *
 * The pure halves are exported too, because they are the part with the rules in
 * them and a host may want to render the same distinctions in HTML — a legend,
 * a selection panel, a list beside the canvas — without a second, quietly
 * different opinion about what "confirmed" means.
 */

export { createTopology } from './topology.ts';
export type {
  SelectionPayload,
  TopologyHandle,
  TopologyOptions,
  UnavailableReason,
} from './topology.ts';

export {
  ORIGINS,
  UPSTREAM_SOURCES,
  TREATMENTS,
  TREATMENT_SPEC,
  effectiveOrigin,
  isOrigin,
  normalizeOrigin,
  originOf,
  originsOf,
  rankOf,
  specFor,
  treatmentFor,
} from './origin.ts';
export type { Origin, Treatment, TreatmentSpec } from './origin.ts';

export { splitDevice, splitDevices } from './conflict.ts';
export type { Claim, DeviceClaimNode } from './conflict.ts';

export { DEFAULT_LAYOUT, collectGroups, layoutTopology } from './layout.ts';
export type {
  LayoutOptions,
  LinkKind,
  SceneLayout,
  SceneLink,
  SceneNode,
  SceneSegment,
  Vec3,
} from './layout.ts';

export {
  hexToRgb,
  packRgb,
  parseColor,
  prefersReducedMotion,
  readColor,
  readDurationMs,
  readFontStack,
  readNumberToken,
  readPalette,
  readToken,
} from './palette.ts';
export type { Rgb, ScenePalette } from './palette.ts';

export { createLedger, trackMaterial } from './resources.ts';
export type { Disposable, DisposeReport, Ledger, TrackedEntry } from './resources.ts';

export { createLifecycle } from './lifecycle.ts';
export type { Lifecycle, LifecycleHost, RenderFn } from './lifecycle.ts';

export type {
  AdjacencyEdge,
  ConflictValue,
  DeviceConflict,
  DeviceGroup,
  DeviceIdentity,
  DevicePort,
  DeviceRow,
  DeviceTreeSnapshot,
  PromotedDevice,
  TopologyInput,
} from './types.ts';
