import { useLayoutEffect, useRef } from 'react';
import { observeReveals } from '@design/motion.js';

/* The one line of glue between React and design/motion.js.
 *
 * motion.js observes the document once at boot. React then renders nodes it has
 * never seen, and an IntersectionObserver does not retroactively pick those up.
 * So every view that contains [data-reveal] elements hands its subtree over
 * after it renders.
 *
 * useLayoutEffect, not useEffect: observeReveals() reads the DOM and assigns
 * --i for the stagger. Doing that before the browser paints means the element
 * never renders once un-staggered and then jumps.
 *
 * IDEMPOTENCE IS motion.js's JOB, NOT OURS. It marks each element with
 * data-reveal-bound and skips the ones it already holds, so calling this on
 * every render - which is what a dependency list of changing data means - costs
 * a querySelectorAll and nothing else. That is deliberate: the alternative is
 * this hook trying to guess when the list changed, and guessing wrong means a
 * newly rendered card stays invisible for the 1200ms until motion.js's safety
 * net fires. A wasted query is cheaper than an invisible row.
 */
export function useReveals<T extends HTMLElement>(deps: readonly unknown[] = []) {
  const ref = useRef<T>(null);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    observeReveals(node);
    // `deps` is the caller's own data. Re-observing when it changes is the
    // point of this hook, so the array is intentionally not a literal.
  }, deps);

  return ref;
}
