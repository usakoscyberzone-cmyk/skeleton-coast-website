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
  return <main><h1>Retention</h1><label>Video <select aria-label="Video" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Select a measured video</option>{summary.videos.map((video) => <option value={video.id} key={video.id}>{video.title}</option>)}</select></label>
    {!summary.videos.length && <p>No videos with persisted metrics are available.</p>}
    {selected && !retention && <p>Loading retention evidence…</p>}
    {retention && !retention.retention && <p>Measured retention is unavailable for this video.</p>}
    {retention?.retention && <MeasuredRetention value={retention.retention} />}
  </main>;
}
function MeasuredRetention({ value }: { value: Record<string, unknown> }) {
  const replay = Array.isArray(value.replay_sections) && value.replay_sections.length > 0;
  const slow = Array.isArray(value.slow_sections) && value.slow_sections.length > 0;
  const candidates = Array.isArray(value.short_candidates) && value.short_candidates.length > 0;
  return <section><h2>Measured retention</h2>
    <p>Opening retention: {typeof value.opening_retention === "number" ? `${(value.opening_retention * 100).toFixed(0)}%` : "Unavailable"}</p>
    <p>First significant drop: {seconds(value.first_significant_drop_seconds)}</p>
    <p>Replay or high-interest: {replay ? "Measured sections available" : "Insufficient measured data"}</p>
    <p>Slow sections: {slow ? "Measured sections available" : "Insufficient measured data"}</p>
    <p>Ending: {value.strong_ending === true ? "Measured strong ending" : value.strong_ending === false ? "Measured ending data does not support a strong-ending marker" : "Insufficient measured data"}</p>
    <p>Possible Short candidates: {candidates ? "Measured sections available" : "Insufficient measured data"}</p>
  </section>;
}
