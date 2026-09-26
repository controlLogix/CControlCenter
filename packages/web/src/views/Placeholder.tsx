import { Card, ViewHeader } from '@/components/ui';
import { useReveals } from '@/motion/useReveals';

/* The six views that are NOT part of this pass.
 *
 * They are real routes with a page that says what they are and where they still
 * live, rather than missing routes. A rail item that navigates nowhere is
 * indistinguishable from one that is broken, and during a migration that
 * ambiguity costs a bug report a week. Saying "not migrated yet, it is still in
 * the vanilla dashboard" is a smaller lie than a blank screen, because it is
 * not a lie at all.
 */

export function Placeholder({ label, hint }: { label: string; hint: string }) {
  const root = useReveals<HTMLDivElement>([label]);

  return (
    <div ref={root} className="placeholder">
      <ViewHeader title={label} stamp="not migrated" />
      <Card label="Status of this view" reveal="up">
        <p>{hint}.</p>
        <p>
          This view has not been rebuilt in React yet. It is still served by the vanilla
          dashboard at <code>dashboard/index.html</code>, and it is unchanged there &mdash; this
          pass covers the shell, <strong>Status</strong> and <strong>Board</strong> only.
        </p>
        <p>
          The route exists on purpose. An icon in the rail that navigates nowhere reads as a
          bug; one that arrives here reads as a plan.
        </p>
      </Card>
    </div>
  );
}
