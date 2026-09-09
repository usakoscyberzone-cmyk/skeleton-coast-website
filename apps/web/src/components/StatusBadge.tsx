import type { RecommendationState } from "../types";

export function StatusBadge({ state }: { state: RecommendationState }) {
  return <span className={`badge badge-${state}`}>{state[0].toUpperCase() + state.slice(1)}</span>;
}
