/* The route module for Board. See src/router.tsx for the convention.
 *
 * A re-export for now, like Status: BoardView.tsx predates the convention. The
 * agent that ports this view whole (TM-075) moves the component and its
 * stylesheet in here, so the view owns exactly one claimable directory. */
export const path = '/board';
export { BoardView as default } from '../BoardView';
