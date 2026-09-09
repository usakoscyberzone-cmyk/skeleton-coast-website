import { useEffect, useState } from "react";
import { getActiveRecommendations, getDashboardSummary, getYouTubeStatus } from "../api/client";
import type { DashboardSummary, Recommendation, YouTubeStatus } from "../types";
import { MetricCard } from "../components/MetricCard";
import { NextActions } from "../components/NextActions";
import { StatusBadge } from "../components/StatusBadge";

const unavailable = "Unavailable";
const number = (value: number | null | undefined) => value == null ? unavailable : value.toLocaleString();

export function HomePage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [status, setStatus] = useState<YouTubeStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getYouTubeStatus().then(setStatus).catch((reason: Error) => setStatusError(reason.message));
    Promise.all([getDashboardSummary(), getActiveRecommendations()])
      .then(([dashboard, actions]) => { setSummary(dashboard); setRecommendations(actions); })
      .catch((reason: Error) => setError(reason.message));
  }, []);
  if (error) return <main><h1>Channel overview</h1><p role="alert">Could not load dashboard: {error}</p></main>;
  if (!summary) return <main><p>Loading dashboard…</p></main>;
  return <main>
    <header className="page-header"><div><p className="eyebrow">Skeleton Coast Fishing Adventures &amp; Tours</p><h1>Channel overview</h1></div><p className="connection">YouTube: {statusError ?? status?.channel_title ?? status?.detail ?? status?.status ?? "checking"}</p></header>
    <NextActions actions={recommendations} />
    <section className="metrics" aria-label="Channel metrics"><MetricCard label="Views" value={number(summary.views.value)} /><MetricCard label="Watch hours" value={summary.watch_minutes.value == null ? unavailable : `${(summary.watch_minutes.value / 60).toFixed(1)} h`} /><MetricCard label="Subscribers gained" value={number(summary.subscribers_gained.value)} /><MetricCard label="Realtime views" value={summary.realtime_views == null ? "Realtime views unavailable" : number(summary.realtime_views)} /></section>
    <section className="dashboard-grid"><section><h2>Current leaders</h2><article className="leader"><span>Top long-form</span><strong>{summary.top_long_form?.title ?? unavailable}</strong><small>{number(summary.top_long_form?.views)} views</small></article><article className="leader"><span>Top Short</span><strong>{summary.top_short?.title ?? unavailable}</strong><small>{number(summary.top_short?.views)} views</small></article></section>
      <section><h2>Traffic-source split</h2>{summary.traffic_sources && Object.keys(summary.traffic_sources).length ? <ul className="traffic">{Object.entries(summary.traffic_sources).map(([name, share]) => <li key={name}>{name} {Math.round(share * 100)}%</li>)}</ul> : <p>Traffic-source data is unavailable.</p>}</section>
      <section><h2>Current video states</h2>{recommendations.length ? <ul className="states">{recommendations.map((video) => <li key={video.id}><span>{video.youtube_video_id}</span><StatusBadge state={video.state} /></li>)}</ul> : <p>No current video states are available.</p>}</section></section>
  </main>;
}
