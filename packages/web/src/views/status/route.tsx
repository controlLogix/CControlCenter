/* The route module for Status. See src/router.tsx for the convention and for
 * why registration is by existing rather than by editing a shared list.
 *
 * A re-export for now: StatusView.tsx predates the convention and is still at
 * src/views/. The agent that ports this view whole (TM-077) moves the
 * component and its stylesheet into this directory, so that everything the
 * view owns is inside one claimable path. Until then this file is the seam and
 * nothing else needs to change. */
export const path = '/status';
export { StatusView as default } from '../StatusView';
