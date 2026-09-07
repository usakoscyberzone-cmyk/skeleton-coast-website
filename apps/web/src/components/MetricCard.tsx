export function MetricCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}
