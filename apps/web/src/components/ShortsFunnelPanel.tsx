import type { ShortPlan } from "../types";

function seconds(value: number) { return `${value}s`; }

export function ShortsFunnelPanel({ plans, error }: { plans: ShortPlan[] | null; error: string | null }) {
  if (error) return <section aria-labelledby="shorts-funnel-heading"><h2 id="shorts-funnel-heading">Shorts funnel</h2><p role="alert">Could not load planned Shorts: {error}</p></section>;
  if (plans === null) return <section aria-labelledby="shorts-funnel-heading" aria-busy="true"><h2 id="shorts-funnel-heading">Shorts funnel</h2><p>Loading planned Shorts…</p></section>;
  return <section aria-labelledby="shorts-funnel-heading"><h2 id="shorts-funnel-heading">Shorts funnel</h2>{plans.length === 0 ? <p>No Shorts have been planned for this project yet.</p> : <div className="short-plan-list">{plans.map((plan) => <article className="short-plan" key={plan.id}><h3>{plan.hook_type}</h3><dl><div><dt>Role</dt><dd>{plan.strategic_role}</dd></div><div><dt>Status</dt><dd>{plan.status}</dd></div><div><dt>Source range</dt><dd>{seconds(plan.source_start_seconds)}–{seconds(plan.source_end_seconds)}</dd></div><div><dt>Target length</dt><dd>{seconds(plan.target_duration_seconds)}</dd></div></dl><p>{plan.on_screen_text}</p><p>CTA: {plan.cta}</p><p className="path">No metrics have been recorded for this advisory plan.</p></article>)}</div>}</section>;
}
