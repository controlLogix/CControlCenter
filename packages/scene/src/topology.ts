/* The 3D device tree. A view, not an alarm — and never a second opinion.
 *
 * WHAT THIS DRAWS, and the one sentence that governs all of it: a device that
 * ANSWERED renders solid; a device we merely INFERRED renders as a wireframe;
 * an address whose sources DISAGREED renders as two nodes, never as one. That
 * is `dashboard/devicetree.py`'s rule, unchanged, expressed in geometry instead
 * of in chips. See origin.ts for the mapping and conflict.ts for the split —
 * both are pure, both are tested, and neither can be bypassed from here.
 *
 * WHAT IT REFUSES TO DO:
 *
 *   It does not fail loudly. No WebGL, a lost context, a shader that will not
 *   compile on a plant-floor Intel driver: the scene disposes itself, the
 *   handle reports `ok: false`, `onUnavailable` fires with a one-word reason,
 *   and the caller falls back to the 2D tree that has always worked. There is
 *   no dialog, no toast and no console error, because this is a nicer way to
 *   look at data the operator can already read — a decorative layer that
 *   interrupts work to announce its own absence has the priority backwards.
 *
 *   It does not move by itself. No auto-rotate, no idle drift, no breathing.
 *   Not "disabled under prefers-reduced-motion" — not implemented, which is
 *   the only version of that guarantee that cannot regress. The single moving
 *   thing is a camera the operator asked to move, and it reads its duration
 *   from --dur-slow, which tokens.css collapses to 0ms under reduced motion.
 *   The contract lives in the stylesheet, as it should.
 *
 *   It does not animate a value. A label carrying a reading is redrawn into
 *   its texture and swapped in the same frame — motion.css's .is-value rule:
 *   "a value that animates between two numbers DISPLAYS NUMBERS THAT WERE
 *   NEVER TRUE for the length of the tween."
 *
 *   It does not let a hover change what a node claims. Highlighting is a
 *   separate outline object that moves between nodes; a node's own material is
 *   never swapped. Pointing at a guess must not make it look confirmed, even
 *   for 100ms.
 *
 *   It does not move the camera on a data refresh. The 2D panel re-polls every
 *   four seconds; a view that re-framed itself on every poll would be unusable
 *   and would look like the plant was moving. The camera is framed once, on the
 *   first tree that has anything in it, and after that only the operator and
 *   focus() move it.
 *
 *   It does not draw a line between two devices unless something observed one.
 *   The hub lines are address arithmetic, and layout.ts says so.
 *
 * FRAMEWORK-AGNOSTIC. A container element and data in, a handle out. No React,
 * no store, no router, no globals. Mounting it is somebody else's file.
 */

import {
  AmbientLight,
  BoxGeometry,
  BufferGeometry,
  CanvasTexture,
  Color,
  DirectionalLight,
  DoubleSide,
  EdgesGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  Raycaster,
  RingGeometry,
  Scene,
  Spherical,
  Sprite,
  SpriteMaterial,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';

import type { TopologyInput } from './types.ts';
import {
  layoutTopology,
  type LayoutOptions,
  type SceneLayout,
  type SceneNode,
} from './layout.ts';
import { readPalette, type Rgb, type ScenePalette } from './palette.ts';
import { createLedger, trackMaterial, type Ledger } from './resources.ts';
import { createLifecycle, type Lifecycle } from './lifecycle.ts';
import type { Treatment } from './origin.ts';

export type UnavailableReason =
  | 'no-container'
  | 'no-webgl'
  | 'init-failed'
  | 'build-failed'
  | 'render-failed'
  | 'context-lost';

/** What a hover or a click hands back. The merged row travels untouched so the
 * host panel can render exactly what the 2D tree does, provenance and all. */
export interface SelectionPayload {
  id: string;
  address: string;
  network: string;
  origin: string;
  treatment: Treatment;
  /** Plain words for the surface the operator is looking at. */
  reading: string;
  conflicted: boolean;
  claimIndex: number;
  claimCount: number;
  claimant: string | null;
  claims: SceneNode['claims'];
  origins: string[];
  corroborating: string[];
  device: SceneNode['device'];
}

export interface TopologyOptions {
  onSelect?: (payload: SelectionPayload | null) => void;
  onHover?: (payload: SelectionPayload | null) => void;
  /** Fires once, with a short reason token. Not an error to show a person. */
  onUnavailable?: (reason: UnavailableReason) => void;
  maxFps?: number;
  /** Capped at 1.5 regardless; a higher request is ignored, a lower one honoured. */
  maxPixelRatio?: number;
  labels?: 'all' | 'none';
  /** Above this many nodes, per-node labels are skipped silently. */
  maxLabels?: number;
  layout?: Partial<LayoutOptions>;
  /** Overrides the token and the media query, for a host that owns the setting. */
  reducedMotion?: boolean;
  doc?: any;
  win?: any;
}

export interface TopologyHandle {
  /** false means: fall back to the 2D tree. Nothing else has gone wrong. */
  readonly ok: boolean;
  setData(input: TopologyInput): void;
  /** Camera to one address. Instant under reduced motion — see the header. */
  focus(address: string | null, options?: { instant?: boolean }): void;
  resize(): void;
  dispose(): void;
  /** Swap a label's text with no tween. The only live-reading path in here. */
  setLabel(address: string, text: string): void;
  select(address: string | null): void;
  readonly element: unknown;
  layout(): SceneLayout | null;
}

const MAX_PIXEL_RATIO = 1.5;
const NODE_SIZE = 3.4;
const MIN_ORBIT = 14;
const MAX_ORBIT = 6000;
const CLICK_SLOP = 4;

/* Neutral fallbacks, echoing palette.ts: when a token cannot be read the scene
 * goes monochrome rather than inventing a hue. Solid-versus-wireframe still
 * answers the only question that matters. */
const FB_TEXT: Rgb = [0.66, 0.66, 0.69];
const FB_LIGHT: Rgb = [0.68, 0.7, 0.72];

function inertHandle(reason: UnavailableReason, options: TopologyOptions): TopologyHandle {
  try {
    options.onUnavailable?.(reason);
  } catch {
    /* the caller's fallback must run even if its own callback throws */
  }
  return {
    ok: false,
    setData() {},
    focus() {},
    resize() {},
    dispose() {},
    setLabel() {},
    select() {},
    element: null,
    layout: () => null,
  };
}

export function createTopology(
  container: any,
  options: TopologyOptions = {},
): TopologyHandle {
  if (!container || typeof container.appendChild !== 'function') {
    return inertHandle('no-container', options);
  }

  const doc = options.doc
    ?? container.ownerDocument
    ?? (typeof document === 'undefined' ? null : document);
  const win = options.win
    ?? doc?.defaultView
    ?? (typeof window === 'undefined' ? null : window);
  if (!doc || !win) return inertHandle('no-container', options);

  let palette: ScenePalette = readPalette(doc);

  // ── the renderer, or the quiet exit ───────────────────────────────────────
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({
      antialias: true,
      alpha: false,
      depth: true,
      stencil: false,
      // A background shader can live with software rendering; a scene with a
      // few hundred meshes cannot, and a 4fps topology is worse than the 2D
      // tree it replaced. Refuse the caveat and let the caller fall back.
      failIfMajorPerformanceCaveat: true,
      powerPreference: 'low-power',
      preserveDrawingBuffer: false,
    });
  } catch {
    return inertHandle('no-webgl', options);
  }

  const rootLedger: Ledger = createLedger('topology');
  let buildLedger: Ledger = createLedger('build');
  rootLedger.defer(() => buildLedger.disposeAll(), 'build-scope');

  let destroyed = false;
  let unavailableFired = false;
  let currentLayout: SceneLayout | null = null;
  let lastInput: TopologyInput = null;
  let framed = false;
  let renderFailures = 0;

  let scene: Scene | null = null;
  let camera: PerspectiveCamera | null = null;
  let lifecycle: Lifecycle | null = null;

  // Layers, so a rebuild empties exactly the part that changed.
  const world = new Group();
  const hubLayer = new Group();
  const linkLayer = new Group();
  const nodeLayer = new Group();
  const labelLayer = new Group();
  const overlayLayer = new Group();

  const nodeMeshes: Mesh[] = [];
  const labelsByAddress = new Map<
    string,
    { draw: (text: string, sub: string) => void; sub: string }
  >();

  const raycaster = new Raycaster();
  const pointerNdc = new Vector2();
  const target = new Vector3();
  const spherical = new Spherical(120, 1.02, 0.72);
  const scratch = new Vector3();
  const panRight = new Vector3();
  const panUp = new Vector3();

  let hovered: SceneNode | null = null;
  let selected: SceneNode | null = null;
  let pointerInside = false;
  let pickWanted = false;
  let hoverOutline: LineSegments | null = null;
  let selectOutline: LineSegments | null = null;

  /* Every material that took a colour from a token, with the token it took it
   * from. A retheme walks this list rather than rebuilding the scene, which is
   * why changing --theme repaints the plant instead of reloading it. */
  const themed: { material: any; token: string; emissive?: string }[] = [];

  interface CameraMove {
    start: number;
    ms: number;
    fromTarget: Vector3;
    toTarget: Vector3;
    fromRadius: number;
    toRadius: number;
  }
  let move: CameraMove | null = null;

  function fail(reason: UnavailableReason): void {
    if (unavailableFired) return;
    unavailableFired = true;
    dispose();
    try {
      options.onUnavailable?.(reason);
    } catch {
      /* see inertHandle */
    }
  }

  try {
    scene = new Scene();
    camera = new PerspectiveCamera(48, 1, 0.5, 20000);

    const ambient = new AmbientLight();
    ambient.intensity = 1.4;
    const key = new DirectionalLight();
    key.intensity = 1.05;
    key.position.set(1, 1.6, 0.8);
    // Lights have no dispose(); tracked anyway so the ledger's inventory is a
    // complete record of what this package put into the scene.
    rootLedger.track(ambient, 'ambient-light');
    rootLedger.track(key, 'key-light');

    world.add(hubLayer, linkLayer, nodeLayer, labelLayer, overlayLayer);
    scene.add(world, ambient, key);

    const canvasEl = renderer.domElement;
    canvasEl.setAttribute('tabindex', '0');
    canvasEl.setAttribute('role', 'application');
    canvasEl.setAttribute('aria-label', 'Device topology. Nothing loaded yet.');
    canvasEl.style.display = 'block';
    canvasEl.style.width = '100%';
    canvasEl.style.height = '100%';
    canvasEl.style.outline = 'none';
    canvasEl.style.touchAction = 'none';
    canvasEl.style.cursor = 'grab';
    container.appendChild(canvasEl);

    rootLedger.defer(() => {
      try { renderer.dispose(); } catch { /* a dead context throws on some drivers */ }
      try { renderer.forceContextLoss?.(); } catch { /* same */ }
      try { canvasEl.parentNode?.removeChild(canvasEl); } catch { /* host already tore down */ }
    }, 'renderer');

    lifecycle = createLifecycle({ doc, win, maxFps: options.maxFps });
    const loop = lifecycle;
    rootLedger.defer(() => loop.dispose(), 'lifecycle');

    // ── shared geometry and materials. One per treatment, never per node ────
    const nodeGeometry = rootLedger.track(
      new BoxGeometry(NODE_SIZE, NODE_SIZE, NODE_SIZE),
      'node-geometry',
    );
    const edgeGeometry = rootLedger.track(new EdgesGeometry(nodeGeometry), 'node-edges');

    function register<T extends { color?: any; emissive?: any }>(
      material: T,
      token: string,
      label: string,
      emissive?: string,
    ): T {
      themed.push({ material, token, emissive });
      trackMaterial(rootLedger, material as any, label);
      return material;
    }

    function paintThemed(): void {
      for (const entry of themed) {
        const rgb = palette.color(entry.token);
        entry.material.color?.setRGB(rgb[0], rgb[1], rgb[2]);
        if (entry.emissive && entry.material.emissive) {
          const e = palette.color(entry.emissive);
          entry.material.emissive.setRGB(e[0], e[1], e[2]);
        }
      }
      ambient.color.setRGB(...palette.color('--text-secondary', FB_TEXT));
      key.color.setRGB(...palette.color('--cool-pale', FB_LIGHT));
      const bg = new Color(palette.void_[0], palette.void_[1], palette.void_[2]);
      if (scene) scene.background = bg;
      renderer.setClearColor(bg, 1);
    }

    const solidMaterials = new Map<Treatment, MeshStandardMaterial | MeshBasicMaterial>();
    function materialFor(node: SceneNode): MeshStandardMaterial | MeshBasicMaterial {
      const existing = solidMaterials.get(node.treatment);
      if (existing) return existing;
      let material: MeshStandardMaterial | MeshBasicMaterial;
      if (node.wireframe) {
        // The wireframe IS the claim: you can see straight through a device
        // nobody has confirmed, from any angle, with the colours off.
        material = new MeshBasicMaterial({
          wireframe: true,
          transparent: node.opacity < 1,
          opacity: node.opacity,
        });
        register(material, node.colorToken, `node-${node.treatment}`);
      } else {
        const standard = new MeshStandardMaterial({
          roughness: 0.55,
          metalness: 0.08,
          transparent: node.opacity < 1,
          opacity: node.opacity,
        });
        if (node.halo === 'accent') standard.emissiveIntensity = 0.22;
        material = standard;
        register(
          standard,
          node.colorToken,
          `node-${node.treatment}`,
          node.halo === 'accent' ? '--accent' : undefined,
        );
      }
      solidMaterials.set(node.treatment, material);
      paintThemed();
      return material;
    }

    const edgeMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 0.7 }),
      '--line-strong', 'node-edge',
    );
    const haloMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 0.9 }),
      '--accent-soft', 'node-halo',
    );
    const hubMaterial = register(
      new MeshBasicMaterial({ transparent: true, opacity: 0.4, side: DoubleSide }),
      '--line-strong', 'hub',
    );
    const segmentLinkMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 0.45 }),
      '--line', 'link-segment',
    );
    // The only use of the hot end of the ramp anywhere in this package.
    // tokens.css: "--accent-hot is for a thing that needs a person NOW". Two
    // sources contradicting each other about a device on a line is that.
    const conflictLinkMaterial = register(
      new LineDashedMaterial({ dashSize: 1.4, gapSize: 0.9, transparent: true, opacity: 0.95 }),
      '--accent-hot', 'link-conflict',
    );
    const observedLinkMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 0.8 }),
      '--line-strong', 'link-observed',
    );
    const inferredLinkMaterial = register(
      new LineDashedMaterial({ dashSize: 1.1, gapSize: 1.4, transparent: true, opacity: 0.55 }),
      '--unknown', 'link-inferred',
    );

    // Highlighting is its own object. It never touches a node's material, so
    // pointing at a guess cannot make it look confirmed. See the header.
    const hoverMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 0.85 }),
      '--text-primary', 'hover-outline',
    );
    hoverOutline = new LineSegments(edgeGeometry, hoverMaterial);
    hoverOutline.scale.setScalar(1.22);
    hoverOutline.visible = false;
    hoverOutline.renderOrder = 2;
    overlayLayer.add(hoverOutline);

    const selectMaterial = register(
      new LineBasicMaterial({ transparent: true, opacity: 1 }),
      '--accent', 'select-outline',
    );
    selectOutline = new LineSegments(edgeGeometry, selectMaterial);
    selectOutline.scale.setScalar(1.42);
    selectOutline.visible = false;
    selectOutline.renderOrder = 3;
    overlayLayer.add(selectOutline);

    paintThemed();

    // ── labels ──────────────────────────────────────────────────────────────
    const labelMode = options.labels ?? 'all';
    const maxLabels = options.maxLabels ?? 120;

    function css(rgb: Rgb): string {
      return `rgb(${Math.round(rgb[0] * 255)} ${Math.round(rgb[1] * 255)} ${Math.round(rgb[2] * 255)})`;
    }

    function makeLabel(
      scope: Ledger,
      text: string,
      sub: string,
      width: number,
      tone: 'primary' | 'muted',
    ): { sprite: Sprite; draw: (text: string, sub: string) => void } {
      const canvas = doc.createElement('canvas');
      canvas.width = 512;
      canvas.height = 160;
      const ctx = canvas.getContext('2d');
      const texture = new CanvasTexture(canvas);
      const material = new SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
      // trackMaterial walks the map slots, so the texture cannot be forgotten.
      trackMaterial(scope, material as any, 'label');

      const head = tone === 'primary' ? palette.label : palette.labelMuted;
      const muted = palette.labelMuted;

      /* Redraw, in full, in this call. No tween and no crossfade: a label is
       * the one place a live reading could enter this scene, and motion.css is
       * explicit that a value swaps instantly while only its container may
       * transition. */
      function draw(nextText: string, nextSub: string): void {
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = `600 54px ${palette.fontMono}`;
        ctx.fillStyle = css(head);
        ctx.fillText(nextText, canvas.width / 2, 52, canvas.width - 16);
        ctx.font = `400 36px ${palette.fontMono}`;
        ctx.fillStyle = css(muted);
        ctx.fillText(nextSub, canvas.width / 2, 112, canvas.width - 16);
        texture.needsUpdate = true;
      }

      draw(text, sub);
      const sprite = new Sprite(material);
      sprite.scale.set(width, width * (canvas.height / canvas.width), 1);
      return { sprite, draw };
    }

    // ── building a device tree into the scene graph ─────────────────────────
    function lineSegmentsFrom(
      points: number[],
      material: LineBasicMaterial | LineDashedMaterial,
      dashed: boolean,
      scope: Ledger,
      label: string,
    ): LineSegments | null {
      if (points.length === 0) return null;
      const geometry = scope.track(new BufferGeometry(), label);
      geometry.setAttribute('position', new Float32BufferAttribute(points, 3));
      const line = new LineSegments(geometry, material);
      if (dashed) line.computeLineDistances();
      return line;
    }

    function build(input: TopologyInput): void {
      lastInput = input;

      hubLayer.clear();
      linkLayer.clear();
      nodeLayer.clear();
      labelLayer.clear();
      nodeMeshes.length = 0;
      labelsByAddress.clear();
      hovered = null;
      if (hoverOutline) hoverOutline.visible = false;

      // Everything the previous tree allocated, released in one call.
      buildLedger.disposeAll();
      buildLedger = createLedger('build');
      const scope = buildLedger;

      const layout = layoutTopology(input, options.layout);
      currentLayout = layout;

      // ── hubs ──────────────────────────────────────────────────────────────
      for (const segment of layout.segments) {
        const ring = scope.track(
          new RingGeometry(Math.max(0.6, segment.radius - 0.5), segment.radius + 0.5, 72),
          `hub-${segment.network}`,
        );
        const disc = new Mesh(ring, hubMaterial);
        disc.rotation.x = -Math.PI / 2;
        disc.position.set(segment.position[0], segment.position[1], segment.position[2]);
        hubLayer.add(disc);

        if (labelMode === 'all') {
          const label = makeLabel(
            scope,
            segment.network,
            // The count that matters, in the 2D panel's own words.
            `${segment.count} found · ${segment.selfReported} identified themselves`,
            segment.radius * 0.8 + 14,
            'muted',
          );
          label.sprite.position.set(
            segment.position[0],
            segment.position[1] - 2.5,
            segment.position[2] + segment.radius + 7,
          );
          labelLayer.add(label.sprite);
        }
      }

      // ── nodes ─────────────────────────────────────────────────────────────
      const labelsAllowed = labelMode === 'all' && layout.nodes.length <= maxLabels;
      for (const node of layout.nodes) {
        const mesh = new Mesh(nodeGeometry, materialFor(node));
        mesh.position.set(node.position[0], node.position[1], node.position[2]);
        mesh.userData.node = node;
        nodeLayer.add(mesh);
        nodeMeshes.push(mesh);

        // A filled node gets a crisp silhouette; a wireframe one already is
        // its own silhouette and gains nothing but clutter from a second.
        if (node.outline === 'solid') {
          mesh.add(new LineSegments(edgeGeometry, edgeMaterial));
        }
        if (node.halo === 'accent') {
          const halo = new LineSegments(edgeGeometry, haloMaterial);
          halo.scale.setScalar(1.16);
          mesh.add(halo);
        }

        if (labelsAllowed) {
          const label = makeLabel(
            scope,
            node.label,
            node.sublabel,
            13,
            node.treatment === 'statement' || node.treatment === 'asserted' ? 'primary' : 'muted',
          );
          label.sprite.position.set(
            node.position[0],
            node.position[1] + NODE_SIZE * 1.3,
            node.position[2],
          );
          labelLayer.add(label.sprite);
          // Keyed by address, first twin wins: setLabel addresses a device, and
          // a conflicted address must not grow a second label to keep in step.
          if (!labelsByAddress.has(node.address)) {
            labelsByAddress.set(node.address, { draw: label.draw, sub: node.sublabel });
          }
        }
      }

      // ── links ─────────────────────────────────────────────────────────────
      const segmentPts: number[] = [];
      const conflictPts: number[] = [];
      const observedPts: number[] = [];
      const inferredPts: number[] = [];
      for (const link of layout.links) {
        const bucket =
          link.kind === 'segment' ? segmentPts
            : link.kind === 'conflict' ? conflictPts
              : link.confidence === 'observed' ? observedPts
                : inferredPts;
        bucket.push(link.a[0], link.a[1], link.a[2], link.b[0], link.b[1], link.b[2]);
      }
      const lineSets: [number[], LineBasicMaterial | LineDashedMaterial, boolean, string][] = [
        [segmentPts, segmentLinkMaterial, false, 'links-segment'],
        [conflictPts, conflictLinkMaterial, true, 'links-conflict'],
        [observedPts, observedLinkMaterial, false, 'links-observed'],
        [inferredPts, inferredLinkMaterial, true, 'links-inferred'],
      ];
      for (const [pts, material, dashed, label] of lineSets) {
        const line = lineSegmentsFrom(pts, material, dashed, scope, label);
        if (line) linkLayer.add(line);
      }

      /* The scene, in words, for anyone not looking at it — the same three
       * counts the 2D panel leads with. A canvas is opaque to a screen reader;
       * this is the only channel that is not. */
      const stats = layout.stats;
      canvasEl.setAttribute(
        'aria-label',
        stats.addresses === 0
          ? 'Device topology. Nothing has answered yet.'
          : `Device topology. ${stats.addresses} address${stats.addresses === 1 ? '' : 'es'} `
            + `across ${stats.segments} subnet${stats.segments === 1 ? '' : 's'}; `
            + `${stats.selfReported} identified themselves; `
            + `${stats.conflicted} where the sources disagree.`,
      );

      if (selected) {
        // A rebuild replaced every mesh. Re-resolve by id so the outline never
        // sits on a node that no longer exists, and drop it if the address is
        // gone rather than leaving a marker on nothing.
        applySelection(layout.nodes.find((n) => n.id === selected!.id) ?? null, false);
      }

      // Once, on the first tree that has anything in it. See the header.
      if (!framed && layout.nodes.length > 0) {
        framed = true;
        frameAll(true);
      }
      loop.invalidate();
    }

    // ── camera ──────────────────────────────────────────────────────────────
    function applyCamera(): void {
      if (!camera) return;
      spherical.radius = Math.min(MAX_ORBIT, Math.max(MIN_ORBIT, spherical.radius));
      spherical.makeSafe();
      scratch.setFromSpherical(spherical);
      camera.position.copy(target).add(scratch);
      camera.lookAt(target);
      camera.updateMatrixWorld();
    }

    function fitDistance(radius: number): number {
      if (!camera) return MIN_ORBIT;
      const vFov = (camera.fov * Math.PI) / 180;
      const hFov = 2 * Math.atan(Math.tan(vFov / 2) * Math.max(0.2, camera.aspect));
      const fov = Math.min(vFov, hFov);
      return Math.max(MIN_ORBIT, (radius * 1.45) / Math.max(0.05, Math.sin(fov / 2)));
    }

    function frameAll(instant: boolean): void {
      if (!currentLayout) return;
      const { center, radius } = currentLayout.bounds;
      goTo(new Vector3(center[0], center[1], center[2]), fitDistance(radius), instant);
    }

    /* Zero means jump. Three ways to get there and any one of them is enough:
     * the caller asked for instant, the host set reducedMotion, or tokens.css
     * collapsed --dur-slow to 0ms under prefers-reduced-motion / data-motion.
     * matchMedia is checked as well as the token because tokens.css's own
     * header is right that two guards are needed — one stops the work and one
     * stops the pixels, and either alone leaves the other half happening. */
    function motionMs(instant: boolean): number {
      if (instant) return 0;
      if (options.reducedMotion === true) return 0;
      if (options.reducedMotion !== false && palette.reducedMotion) return 0;
      return palette.focusMs;
    }

    function goTo(nextTarget: Vector3, nextRadius: number, instant: boolean): void {
      const ms = motionMs(instant);
      if (ms <= 0) {
        move = null;
        target.copy(nextTarget);
        spherical.radius = nextRadius;
        applyCamera();
        loop.invalidate();
        return;
      }
      move = {
        start: win.performance?.now?.() ?? Date.now(),
        ms,
        fromTarget: target.clone(),
        toTarget: nextTarget.clone(),
        fromRadius: spherical.radius,
        toRadius: nextRadius,
      };
      loop.invalidate();
    }

    // tokens.css's --ease-out as a function. Deliberately NOT --ease-spring: an
    // overshoot would, for two frames, frame a part of the plant nobody asked
    // to see, and tokens.css reserves the spring for a thing being released.
    const easeOut = (t: number): number => 1 - Math.pow(1 - t, 3);

    // ── picking ─────────────────────────────────────────────────────────────
    function payloadFor(node: SceneNode | null): SelectionPayload | null {
      if (!node) return null;
      return {
        id: node.id,
        address: node.address,
        network: node.network,
        origin: node.origin,
        treatment: node.treatment,
        reading: node.reading,
        conflicted: node.conflicted,
        claimIndex: node.claimIndex,
        claimCount: node.claimCount,
        claimant: node.claimant,
        claims: node.claims,
        origins: node.origins,
        corroborating: node.corroborating,
        device: node.device,
      };
    }

    function pick(): SceneNode | null {
      if (!pointerInside || !camera || nodeMeshes.length === 0) return null;
      raycaster.setFromCamera(pointerNdc, camera);
      for (const hit of raycaster.intersectObjects(nodeMeshes, false)) {
        const node = (hit.object as Mesh).userData?.node as SceneNode | undefined;
        if (node) return node;
      }
      return null;
    }

    function applyHover(node: SceneNode | null): void {
      if (node === hovered) return;
      hovered = node;
      if (hoverOutline) {
        hoverOutline.visible = Boolean(node);
        if (node) hoverOutline.position.set(node.position[0], node.position[1], node.position[2]);
      }
      canvasEl.style.cursor = node ? 'pointer' : 'grab';
      try {
        options.onHover?.(payloadFor(node));
      } catch {
        /* a host callback that throws is not this renderer's to surface */
      }
    }

    function applySelection(node: SceneNode | null, notify: boolean): void {
      selected = node;
      if (selectOutline) {
        selectOutline.visible = Boolean(node);
        if (node) selectOutline.position.set(node.position[0], node.position[1], node.position[2]);
      }
      if (notify) {
        try {
          options.onSelect?.(payloadFor(node));
        } catch {
          /* as above */
        }
      }
      loop.invalidate();
    }

    // ── input. Every listener goes through lifecycle.on, so dispose gets it ──
    let dragButton = -1;
    let dragX = 0;
    let dragY = 0;
    let dragDistance = 0;
    const activePointers = new Map<number, { x: number; y: number }>();
    let pinchDistance = 0;

    function setNdc(event: any): void {
      const rect = canvasEl.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointerNdc.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointerNdc.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }

    loop.on(canvasEl, 'pointerdown', (event: any) => {
      activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (activePointers.size === 2) {
        const [a, b] = [...activePointers.values()];
        pinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
        dragButton = -1;
        return;
      }
      dragButton = event.button ?? 0;
      dragX = event.clientX;
      dragY = event.clientY;
      dragDistance = 0;
      try { canvasEl.setPointerCapture?.(event.pointerId); } catch { /* not captured */ }
      try { canvasEl.focus?.({ preventScroll: true }); } catch { /* not focusable */ }
    });

    loop.on(canvasEl, 'pointermove', (event: any) => {
      pointerInside = true;
      if (activePointers.has(event.pointerId)) {
        activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      }

      if (activePointers.size === 2) {
        const [a, b] = [...activePointers.values()];
        const next = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinchDistance > 0 && next > 0) {
          spherical.radius *= pinchDistance / next;
          move = null;
          applyCamera();
          loop.invalidate();
        }
        pinchDistance = next;
        return;
      }

      setNdc(event);

      if (dragButton === -1) {
        // Hover is resolved inside the frame, so a fast mouse costs one
        // raycast per frame rather than one per pointer event.
        pickWanted = true;
        loop.invalidate();
        return;
      }

      const dx = event.clientX - dragX;
      const dy = event.clientY - dragY;
      dragX = event.clientX;
      dragY = event.clientY;
      dragDistance += Math.abs(dx) + Math.abs(dy);

      if (dragButton === 1 || dragButton === 2 || event.shiftKey) {
        const scale = spherical.radius * 0.0018;
        camera?.matrixWorld.extractBasis(panRight, panUp, scratch);
        target.addScaledVector(panRight, -dx * scale);
        target.addScaledVector(panUp, dy * scale);
      } else {
        // No damping, no inertia. The camera is exactly where the hand put it,
        // which is also why there is nothing here to switch off for reduced
        // motion: released, it stops.
        spherical.theta -= dx * 0.005;
        spherical.phi -= dy * 0.005;
      }
      move = null;   // the operator took the wheel; abandon whatever focus() started
      applyCamera();
      loop.invalidate();
    });

    function endPointer(event: any): void {
      activePointers.delete(event.pointerId);
      if (activePointers.size < 2) pinchDistance = 0;
      if (dragButton === -1) return;
      const wasClick = dragDistance <= CLICK_SLOP;
      dragButton = -1;
      try { canvasEl.releasePointerCapture?.(event.pointerId); } catch { /* already gone */ }
      if (!wasClick) return;
      setNdc(event);
      pointerInside = true;
      applySelection(pick(), true);
    }

    loop.on(canvasEl, 'pointerup', endPointer);
    loop.on(canvasEl, 'pointercancel', endPointer);

    loop.on(canvasEl, 'pointerleave', () => {
      pointerInside = false;
      applyHover(null);
      loop.invalidate();
    });

    loop.on(canvasEl, 'wheel', (event: any) => {
      event.preventDefault?.();
      spherical.radius *= Math.exp((event.deltaY ?? 0) * 0.0012);
      move = null;
      applyCamera();
      loop.invalidate();
    }, { passive: false });

    loop.on(canvasEl, 'keydown', (event: any) => {
      const step = 0.1;
      let handled = true;
      switch (event.key) {
        case 'ArrowLeft': spherical.theta += step; break;
        case 'ArrowRight': spherical.theta -= step; break;
        case 'ArrowUp': spherical.phi -= step * 0.7; break;
        case 'ArrowDown': spherical.phi += step * 0.7; break;
        case '+': case '=': spherical.radius *= 0.85; break;
        case '-': case '_': spherical.radius *= 1.18; break;
        case 'Home': frameAll(true); break;
        case 'Escape': applySelection(null, true); break;
        default: handled = false;
      }
      if (!handled) return;
      event.preventDefault?.();
      move = null;
      applyCamera();
      loop.invalidate();
    });

    // ── resize ──────────────────────────────────────────────────────────────
    function resize(): void {
      if (destroyed || !camera) return;
      const width = Math.max(1, Math.floor(container.clientWidth || 1));
      const height = Math.max(1, Math.floor(container.clientHeight || 1));
      // Capped, exactly as design/field.js caps it. A retina panel rendering a
      // topology at 3x is spending triple the fill rate on pixels nobody can
      // resolve from where they are standing.
      renderer.setPixelRatio(Math.min(
        options.maxPixelRatio ?? MAX_PIXEL_RATIO,
        MAX_PIXEL_RATIO,
        win.devicePixelRatio || 1,
      ));
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      applyCamera();
      loop.invalidate();
    }

    if (typeof win.ResizeObserver === 'function') {
      const observer = new win.ResizeObserver(() => resize());
      observer.observe(container);
      rootLedger.defer(() => observer.disconnect(), 'resize-observer');
    } else {
      loop.on(win, 'resize', () => resize());
    }

    // A driver reset must not leave a black rectangle where the data was. Same
    // handling as design/field.js: take it out and stay out.
    loop.on(canvasEl, 'webglcontextlost', (event: any) => {
      event.preventDefault?.();
      fail('context-lost');
    });

    /* Retheming the product rethemes the scene, because every colour in it came
     * from a token. Two triggers, because the product has two switches: the OS
     * colour scheme, and :root[data-theme] / :root[data-motion], which
     * tokens.css describes as "an explicit operator switch, independent of the
     * OS setting" for a plant floor machine. */
    function retheme(): void {
      if (destroyed) return;
      palette = readPalette(doc);
      paintThemed();
      // Label colour is baked into a canvas texture, so the labels are the one
      // thing a repaint cannot reach. Rebuild them from the tree already held.
      build(lastInput);
    }

    if (typeof win.matchMedia === 'function') {
      try {
        const query = win.matchMedia('(prefers-color-scheme: dark)');
        loop.on(query as any, 'change', retheme);
      } catch { /* an old matchMedia with no addEventListener; not worth a shim */ }
    }
    if (typeof win.MutationObserver === 'function' && doc.documentElement) {
      const observer = new win.MutationObserver(retheme);
      observer.observe(doc.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme', 'data-motion'],
      });
      rootLedger.defer(() => observer.disconnect(), 'theme-observer');
    }

    // ── the frame ───────────────────────────────────────────────────────────
    loop.start((now: number) => {
      if (destroyed || !scene || !camera) return false;
      try {
        let again = false;

        if (pickWanted) {
          pickWanted = false;
          applyHover(pick());
        }

        if (move) {
          const t = move.ms <= 0 ? 1 : Math.min(1, (now - move.start) / move.ms);
          const k = easeOut(t);
          target.lerpVectors(move.fromTarget, move.toTarget, k);
          spherical.radius = move.fromRadius + (move.toRadius - move.fromRadius) * k;
          applyCamera();
          if (t >= 1) move = null;
          else again = true;
        }

        renderer.render(scene, camera);
        renderFailures = 0;
        return again;
      } catch {
        /* Three strikes. One throw can be a transient; a render that fails
         * every frame is a driver that is not going to recover, and spinning
         * on it is worse for the operator than the 2D tree they already had. */
        renderFailures += 1;
        if (renderFailures >= 3) fail('render-failed');
        return false;
      }
    });

    resize();
    build(null);

    // ── the handle ──────────────────────────────────────────────────────────
    function focus(address: string | null, opts: { instant?: boolean } = {}): void {
      if (destroyed) return;
      if (!address || !currentLayout) {
        frameAll(Boolean(opts.instant));
        return;
      }
      const matches = currentLayout.nodes.filter((n) => n.address === address);
      if (matches.length === 0) {
        frameAll(Boolean(opts.instant));
        return;
      }
      // A conflicted address is two nodes; framing is centred on both, so what
      // fills the screen is the disagreement rather than one side of it.
      const centre = new Vector3();
      for (const node of matches) {
        centre.add(new Vector3(node.position[0], node.position[1], node.position[2]));
      }
      centre.divideScalar(matches.length);
      let spread = NODE_SIZE * 2.4;
      for (const node of matches) {
        const p = new Vector3(node.position[0], node.position[1], node.position[2]);
        spread = Math.max(spread, centre.distanceTo(p) + NODE_SIZE * 2);
      }
      goTo(centre, fitDistance(spread), Boolean(opts.instant));
    }

    return {
      get ok() { return !destroyed; },
      setData(input: TopologyInput) {
        if (destroyed) return;
        try {
          build(input);
        } catch {
          fail('build-failed');
        }
      },
      focus,
      resize,
      dispose,
      setLabel(address: string, text: string) {
        if (destroyed) return;
        const entry = labelsByAddress.get(address);
        if (!entry) return;
        // Instant. See the header and motion.css's .is-value.
        entry.draw(text, entry.sub);
        loop.invalidate();
      },
      select(address: string | null) {
        if (destroyed || !currentLayout) return;
        applySelection(
          address ? currentLayout.nodes.find((n) => n.address === address) ?? null : null,
          true,
        );
      },
      get element() { return destroyed ? null : renderer.domElement; },
      layout: () => currentLayout,
    };
  } catch {
    // Anything at all during construction: unwind whatever was built and hand
    // back an inert handle. The caller renders the 2D tree and nobody is told.
    try { rootLedger.disposeAll(); } catch { /* nothing left to do */ }
    destroyed = true;
    return inertHandle('init-failed', options);
  }

  /* Hoisted, so `fail()` above can reach it. Reverse order, every step
   * guarded, nothing logged — see resources.ts for why the ledger rather than
   * a hand-maintained list of things to free. */
  function dispose(): void {
    if (destroyed) return;
    destroyed = true;
    currentLayout = null;
    lastInput = null;
    nodeMeshes.length = 0;
    labelsByAddress.clear();
    themed.length = 0;
    hovered = null;
    selected = null;
    hoverOutline = null;
    selectOutline = null;
    move = null;
    try {
      hubLayer.clear();
      linkLayer.clear();
      nodeLayer.clear();
      labelLayer.clear();
      overlayLayer.clear();
      world.clear();
      scene?.clear();
    } catch { /* a partially built scene is still worth unwinding */ }
    rootLedger.disposeAll();
    scene = null;
    camera = null;
    lifecycle = null;
  }
}
