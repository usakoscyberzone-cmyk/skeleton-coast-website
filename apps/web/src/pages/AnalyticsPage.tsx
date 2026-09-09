import { useEffect, useState } from "react";
import { getDashboardSummary } from "../api/client";
import type { DashboardSummary, MetricTotal } from "../types";

const topics = ["Fishing", "Namibia travel", "Angola", "History", "4x4", "Current events"];
const display = (metric: MetricTotal, format?: (value: number) => string) => metric.value === null ? "Unavailable" : format ? format(metric.value) : metric.value.toLocaleString();
const coverage = (metric: MetricTotal) => metric.coverage ? `${metric.coverage} video${metric.coverage === 1 ? "" : "s"}` : "no measured videos";

export function AnalyticsPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getDashboardSummary().then(setSummary).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <main><h1>Analytics</h1><p role="alert">Unable to load analytics: {error}</p></main>;
  if (!summary) return <main><h1>Analytics</h1><p>Loading analytics…</p></main>;
  const metrics: [string, MetricTotal, ((value: number) => string)?][] = [
    ["Impressions", summary.impressions], ["CTR", summary.ctr, (value) => `${(value * 100).toFixed(1)}%`], ["Views", summary.views], ["AVD", summary.avg_view_duration_seconds, (value) => `${value}s`],
    ["Average percentage viewed", summary.average_percentage_viewed, (value) => `${(value * 100).toFixed(1)}%`], ["Watch time", summary.watch_minutes, (value) => `${value} min`], ["Subscribers gained", summary.subscribers_gained],
    ["Subscriber conversion", summary.subscriber_conversion_rate, (value) => `${(value * 100).toFixed(2)}%`], ["Returning viewers", summary.returning_viewers],
  ];
  return <main><h1>Analytics</h1><section aria-label="Metrics">{metrics.map(([label, metric, formatter]) => <article key={label}><h2>{label}</h2><p>{display(metric, formatter)}</p><small>Coverage: {coverage(metric)}</small></article>)}</section>
    <section><h2>Traffic sources</h2>{["Browse", "Suggested", "Search", "External", "Shorts Feed"].map((source) => <p key={source}>{source} {summary.traffic_sources[source] === undefined ? "Unavailable" : `${(summary.traffic_sources[source] * 100).toFixed(0)}%`} {summary.traffic_source_coverage[source] ? `(${summary.traffic_source_coverage[source]} videos)` : "(no measured videos)"}</p>)}</section>
    <section><h2>Views by time window</h2>{([ ["1 hour", summary.views_1h], ["24 hours", summary.views_24h], ["7 days", summary.views_7d] ] as [string, MetricTotal][]).map(([label, metric]) => <p key={label}>{label}: {display(metric)} <small>({coverage(metric)})</small></p>)}</section>
    <section><h2>Topics</h2>{topics.map((topic) => { const metric = summary.topics[topic] ?? { value: null, coverage: 0 }; return <div key={topic}><span>{topic}</span><p>{`${topic}: ${display(metric)} (${coverage(metric)})`}</p></div>; })}</section>
  </main>;
}
