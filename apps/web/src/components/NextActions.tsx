import type { Recommendation } from "../types";
import { StatusBadge } from "./StatusBadge";

export function NextActions({ actions }: { actions: Recommendation[] }) {
  return <section className="next-actions" aria-labelledby="next-actions-title">
    <div><p className="eyebrow">Prioritized guidance</p><h2 id="next-actions-title">What should I do next?</h2></div>
    {actions.length === 0 ? <p>No active action is ready. Keep gathering enough channel data before changing packaging.</p> :
      <ol>{actions.map((item) => <li key={item.id}><StatusBadge state={item.state} /><strong>{item.action}</strong><p>{item.reason}</p><small>Confidence: {item.confidence}. Data used: {Object.keys(item.data_used).join(", ") || "available channel data"}.</small></li>)}</ol>}
  </section>;
}
