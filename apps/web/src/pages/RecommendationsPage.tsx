import { useEffect, useState } from "react";
import { getActiveRecommendations } from "../api/client";
import type { Recommendation } from "../types";
const rank = { red: 0, amber: 1, green: 2 };
export function RecommendationsPage() {
  const [items, setItems] = useState<Recommendation[] | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { getActiveRecommendations().then((value) => setItems(value.sort((a, b) => rank[a.state] - rank[b.state]))).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <main><h1>Recommendations</h1><p role="alert">Unable to load recommendations: {error}</p></main>;
  if (!items) return <main><h1>Recommendations</h1><p>Loading recommendations…</p></main>;
  if (!items.length) return <main><h1>Recommendations</h1><p>No active recommendations are available.</p></main>;
  return <main><h1>Recommendations</h1>{items.map((item) => <article key={item.id}><h2>{item.state[0].toUpperCase() + item.state.slice(1)}</h2><p><strong>Action:</strong> {item.action}</p><p><strong>Reason:</strong> {item.reason}</p><p><strong>Confidence:</strong> {item.confidence}</p><p><strong>Data used:</strong> {Object.entries(item.data_used).map(([key, value]) => `${key}: ${String(value)}`).join(", ") || "Unavailable"}</p></article>)}</main>;
}
