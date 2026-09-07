import { useEffect, useState } from "react";
import { getLearningPatterns } from "../api/client";
import type { LearningPattern } from "../types";
export function LearningPage() {
  const [patterns, setPatterns] = useState<LearningPattern[] | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { getLearningPatterns().then(setPatterns).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <main><h1>Learning</h1><p role="alert">Unable to load learning patterns: {error}</p></main>;
  if (!patterns) return <main><h1>Learning</h1><p>Loading persisted learning patterns…</p></main>;
  if (!patterns.length) return <main><h1>Learning</h1><p>No persisted learning patterns are available yet.</p></main>;
  return <main><h1>Learning</h1>{patterns.map((pattern) => <article key={pattern.id}><h2>{pattern.topic}: {pattern.pattern_type}</h2><p>{pattern.summary}</p><p>Confidence: {pattern.confidence}</p><p>Evidence: {pattern.evidence_count}</p></article>)}</main>;
}
