/* Types for the shared design system.
 *
 * design/ is plain ES modules by design - the vanilla dashboard and this React
 * app both import them, so the two cannot drift into two motion languages
 * during the migration. That means there are no .d.ts files next to them, and
 * TypeScript needs these declarations to see across the package boundary.
 *
 * These are declarations of an EXISTING contract, not a place to change it. If
 * a signature here disagrees with design/motion.js, the .js file is right.
 */

declare module '@design/motion.js' {
  /** Add .is-in and .is-settled to every reveal target under `root`. Idempotent. */
  export function revealEverything(root?: ParentNode): void;

  /**
   * Observe reveal targets under `root`. Safe to call repeatedly: a node already
   * bound is skipped and a node already revealed is never re-hidden. Call this
   * after rendering new nodes - React does not tell motion.js that it rendered.
   */
  export function observeReveals(root?: ParentNode): void;

  /** Generate and append the tiled noise layer. No-op if one already exists. */
  export function installGrain(): void;

  /** Boot the reveal observer, claim the document, install grain. Call once. */
  export function startMotion(options?: { grain?: boolean }): void;
}

declare module '@design/field.js' {
  export interface FieldHandle {
    stop(): void;
    /** Re-read the colour tokens; call after a theme change. */
    syncColours?(): void;
    canvas?: HTMLCanvasElement;
  }

  /**
   * Start the WebGL background. Returns a handle whose stop() is always safe to
   * call - on a machine with no WebGL2 it returns a handle that does nothing,
   * because this is decoration and decoration gets no error surface.
   */
  export function startField(options?: {
    maxFps?: number;
    scale?: number;
    warpScale?: number;
    noiseScale?: number;
  }): FieldHandle;
}
