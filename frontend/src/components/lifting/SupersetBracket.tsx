import type { ReactNode } from "react";

interface Props {
  /** Number of distinct exercises in this superset group. */
  exerciseCount: number;
  /** Minimum set count across the grouped exercises — interpreted as the
   *  number of rounds the superset was performed for. */
  rounds: number;
  children: ReactNode;
}

/**
 * Wraps adjacent exercise cards that share a non-null `superset_group_id`
 * with a brand-green left rail and a small header label, matching the
 * recording-screen idiom (see `ExerciseCard.tsx`: linked cards get a
 * `border-l-2 border-l-brand-green`).
 */
export function SupersetBracket({ exerciseCount, rounds, children }: Props) {
  return (
    <div
      data-testid="superset-bracket"
      className="relative border-l-2 border-l-brand-green pl-3 mb-3"
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-brand-green mb-2">
        Superset · {exerciseCount} {exerciseCount === 1 ? "exercise" : "exercises"}
        {" · "}
        {rounds} {rounds === 1 ? "round" : "rounds"}
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

export default SupersetBracket;
