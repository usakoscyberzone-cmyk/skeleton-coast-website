import { useEffect, useState } from "react";
import { getDashboardSummary, getRetention } from "../api/client";
import type { DashboardSummary, RetentionData } from "../types";

const seconds = (value: unknown) => typeof value === "number" ? `${value}s` : "Unavailable";
export function RetentionPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null); const [selected, setSelected] = useState("");
  const [retention, setRetention] = useState<RetentionData | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { getDashboardSummary().then(setSummary).catch((reason: Error) => setError(reason.message)); }, []);
  useEffect(() => { if (!selected) { setRetention(null); return; } getRetention(selected).then(setRetention).catch((reason: Error) => setError(reason.message)); }, [selected]);
  if (error) return <main><h1>Retention</h1><p role="alert">Unable to load retention: {error}</p></main>;
  if (!summary) return <main><h1>Retention</h1><p>Loading videos…</p></main>;
  return <main><h1>Retention</h1><label>Video <select aria-label="Video" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Select a measured video</option>{summary.retention_videos.map((video) => <option value={video.id} key={video.id}>{video.title}</option>)}</select></label>
    {!summary.retention_videos.length && <p>No videos with measured retention are available.</p>}
    {selected && !retention && <p>Loading retention evidence…</p>}
    {retention && (!retention.retention || !retention.retention.length) && <p>Measured retention is unavailable for this video.</p>}
    {retention?.retention && retention.retention.length > 0 && <MeasuredRetention points={retention.retention} />}
  </main>;
}
function MeasuredRetention({ points }: { points: NonNullable<RetentionData["retention"]> }) {
  const ordered = [...points].sort((left, right) => left.elapsed_ratio - right.elapsed_ratio);
  const opening = ordered[0]; const ending = ordered[ordered.length - 1];
  return <section><h2>Measured retention</h2>
    <p>Opening retention (measured): {(opening.audience_retention * 100).toFixed(0)}%</p>
    <p>First significant drop: Insufficient measured data (no documented threshold).</p>
    <p>Replay or high-interest: Insufficient measured data (no documented threshold).</p>
    <p>Slow sections: Insufficient measured data (no documented threshold).</p>
    <p>Ending (measured): {(ending.audience_retention * 100).toFixed(0)}%</p>
    <p>Possible Short candidates: Insufficient measured data (no documented threshold).</p>
  </section>;
}
