/* The ledger: nothing is created in this scene without being written down.
 *
 * WHY A LEDGER RATHER THAN A dispose() THAT LISTS THINGS. Because the listing
 * kind is always correct on the day it is written and wrong six weeks later.
 * Somebody adds a texture for a label, the teardown function still names the
 * five objects that existed before, and the leak is invisible: a WebGL scene
 * that leaks does not throw, it just makes the machine slower every time the
 * operator switches views, until a shift ends with a tab that has to be
 * closed. This repo already documents the terminal-side version of exactly
 * that bug; this is its 3D twin, and a list maintained by hand is how it gets
 * reintroduced.
 *
 * So allocation goes through `track()` and teardown is `disposeAll()`, which
 * means the two cannot drift: an object that was never tracked is an object
 * that was never created by this package, and `resources.test.mjs` asserts
 * that after a full cycle the ledger is empty and every tracked object saw
 * exactly one dispose() call.
 *
 * SCOPES, because setData() rebuilds. A build scope holds everything belonging
 * to the current device tree and is disposed wholesale on the next setData; the
 * root scope holds the renderer and the things that outlive a rebuild. A child
 * scope is disposed by its parent too, so dispose() cannot miss one.
 *
 * NO three.js IMPORT HERE. It only needs objects with a dispose method, which
 * is what makes the completeness test possible with fakes and no GPU.
 */

export interface Disposable {
  dispose?: () => void;
}

export interface TrackedEntry {
  label: string;
  value: unknown;
}

export interface DisposeReport {
  /** Objects whose dispose() was called and returned. */
  disposed: number;
  /** Tracked objects with no dispose method — lights, groups, plain data. */
  released: number;
  /** dispose() threw. Recorded, never rethrown: see disposeAll. */
  failed: { label: string; error: unknown }[];
  /** Child scopes disposed as part of this one. */
  children: number;
}

export interface Ledger {
  readonly name: string;
  /** Write an object down and hand it straight back, so it can wrap a `new`. */
  track<T>(value: T, label?: string): T;
  /** A nested scope, disposed with its parent. */
  child(name: string): Ledger;
  /** A teardown step that is not an object — a listener, an observer, a RAF. */
  defer(fn: () => void, label?: string): void;
  size(): number;
  outstanding(): TrackedEntry[];
  disposed(): boolean;
  disposeAll(): DisposeReport;
}

let counter = 0;

export function createLedger(name = 'scene'): Ledger {
  const entries: TrackedEntry[] = [];
  const children: Ledger[] = [];
  const deferred: { label: string; fn: () => void }[] = [];
  let dead = false;
  const id = (counter += 1);

  const ledger: Ledger = {
    name: `${name}#${id}`,

    track<T>(value: T, label?: string): T {
      /* Tracking after disposal would be a silent leak of the worst kind: the
       * object is real, the scene is gone, and nothing will ever call its
       * dispose. Dispose it on the spot instead and return it anyway, so the
       * caller's expression still evaluates and the mistake is contained. */
      if (dead) {
        try {
          (value as Disposable)?.dispose?.();
        } catch {
          /* already tearing down */
        }
        return value;
      }
      entries.push({ label: label ?? typeofLabel(value), value });
      return value;
    },

    child(childName: string): Ledger {
      const kid = createLedger(`${name}/${childName}`);
      if (dead) {
        kid.disposeAll();
        return kid;
      }
      children.push(kid);
      return kid;
    },

    defer(fn: () => void, label = 'deferred'): void {
      if (typeof fn !== 'function') return;
      if (dead) {
        try { fn(); } catch { /* already tearing down */ }
        return;
      }
      deferred.push({ label, fn });
    },

    size(): number {
      return entries.length + deferred.length
        + children.reduce((n, c) => n + c.size(), 0);
    },

    outstanding(): TrackedEntry[] {
      const out: TrackedEntry[] = [...entries];
      for (const kid of children) out.push(...kid.outstanding());
      return out;
    },

    disposed(): boolean {
      return dead;
    },

    /* Reverse order, so a thing disposes before whatever it was built on.
     *
     * Every step is wrapped. A driver that throws out of one geometry's
     * dispose() must not strand the other forty behind it — the whole point of
     * this function is that it finishes. Failures are counted and returned;
     * nothing is logged, because this package degrades silently by contract
     * and a console error on a view switch is an error surface. */
    disposeAll(): DisposeReport {
      const report: DisposeReport = { disposed: 0, released: 0, failed: [], children: 0 };
      if (dead) return report;
      dead = true;

      for (let i = children.length - 1; i >= 0; i -= 1) {
        const sub = children[i].disposeAll();
        report.disposed += sub.disposed;
        report.released += sub.released;
        report.failed.push(...sub.failed);
        report.children += 1 + sub.children;
      }
      children.length = 0;

      for (let i = deferred.length - 1; i >= 0; i -= 1) {
        const step = deferred[i];
        try {
          step.fn();
          report.disposed += 1;
        } catch (error) {
          report.failed.push({ label: step.label, error });
        }
      }
      deferred.length = 0;

      for (let i = entries.length - 1; i >= 0; i -= 1) {
        const entry = entries[i];
        const value = entry.value as Disposable | null;
        const fn = value && typeof value === 'object' ? value.dispose : undefined;
        if (typeof fn !== 'function') {
          report.released += 1;
          continue;
        }
        try {
          fn.call(value);
          report.disposed += 1;
        } catch (error) {
          report.failed.push({ label: entry.label, error });
        }
      }
      entries.length = 0;

      return report;
    },
  };

  return ledger;
}

function typeofLabel(value: unknown): string {
  if (value === null || value === undefined) return 'nothing';
  const ctor = (value as { constructor?: { name?: string } })?.constructor?.name;
  return ctor || typeof value;
}

/* three.js hangs a material's textures off named properties rather than a
 * list, so a material that is disposed without its maps having been disposed
 * leaks GPU memory that nothing else references. These are every map slot the
 * standard, basic, line and sprite materials use. Called by topology.ts on
 * every material it tracks, which is why a texture cannot be forgotten by
 * being assigned somewhere unusual. */
const TEXTURE_SLOTS = [
  'map', 'alphaMap', 'aoMap', 'bumpMap', 'displacementMap', 'emissiveMap',
  'envMap', 'lightMap', 'metalnessMap', 'normalMap', 'roughnessMap',
  'specularMap', 'gradientMap', 'matcap', 'clearcoatMap', 'sheenColorMap',
] as const;

/** Track a material AND whatever textures are hanging off it. */
export function trackMaterial<T extends Record<string, any>>(
  ledger: Ledger,
  material: T,
  label = 'material',
): T {
  if (!material || typeof material !== 'object') return material;
  for (const slot of TEXTURE_SLOTS) {
    const texture = material[slot];
    if (texture && typeof texture === 'object' && typeof texture.dispose === 'function') {
      ledger.track(texture, `${label}.${slot}`);
    }
  }
  return ledger.track(material, label);
}
