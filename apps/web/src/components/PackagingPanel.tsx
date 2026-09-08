import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { getPackagingCandidates, registerThumbnail, savePackagingCandidates } from "../api/client";
import type { PackagingCandidate, PackagingDocument, PackagingLabel, PackagingScores, ThumbnailAspect } from "../types";
import "./PackagingPanel.css";

const criteria: Array<[keyof PackagingScores, string]> = [
  ["curiosity", "Curiosity"], ["clarity", "Clarity"], ["search_relevance", "Search relevance"],
  ["audience_fit", "Audience fit"], ["uniqueness", "Uniqueness"],
  ["title_thumbnail_complementarity", "Title/thumbnail complementarity"],
];
const labels: PackagingLabel[] = ["A", "B", "C"];

function CandidateCard({ candidate }: { candidate: PackagingCandidate }) {
  return <article className="packaging-candidate">
    <h3>Candidate {candidate.label}</h3>
    <div className="packaging-pair"><strong>{candidate.title}</strong><p>{candidate.thumbnail.file} · {candidate.thumbnail.aspect}</p></div>
    <dl><div><dt>Hook</dt><dd>{candidate.hook}</dd></div><div><dt>SEO description</dt><dd>{candidate.seo_description}</dd></div><div><dt>Tags</dt><dd>{candidate.tags.join(", ")}</dd></div><div><dt>Pinned comment</dt><dd>{candidate.pinned_comment}</dd></div><div><dt>Chapters</dt><dd>{candidate.chapters}</dd></div><div><dt>Playlist</dt><dd>{candidate.playlist}</dd></div><div><dt>Next-video CTA</dt><dd>{candidate.next_video_cta}</dd></div></dl>
    <ul className="score-list">{criteria.map(([key, label]) => <li key={key}><span>{label} <small>(advisory)</small></span><strong>{candidate.scores[key]}/100</strong></li>)}</ul>
    <p><strong>Why:</strong> {candidate.rationale}</p>
  </article>;
}

const initialScores = (): PackagingScores => ({ curiosity: 50, clarity: 50, search_relevance: 50, audience_fit: 50, uniqueness: 50, title_thumbnail_complementarity: 50 });

export function PackagingPanel({ projectId }: { projectId: string | number }) {
  const [document, setDocument] = useState<PackagingDocument | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [scores, setScores] = useState(initialScores);

  useEffect(() => { getPackagingCandidates(projectId).then(setDocument).catch((error: Error) => setLoadError(error.message)); }, [projectId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaveError(null); setSaved(false);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const label = String(form.get("label")) as PackagingLabel;
    const aspect = String(form.get("aspect")) as ThumbnailAspect;
    const suffix = aspect === "16:9" ? "16x9" : "9x16";
    const candidate: PackagingCandidate = {
      label, title: String(form.get("title")), thumbnail: { aspect, file: `Thumbnails/thumbnail-${label}-${suffix}.png` },
      hook: String(form.get("hook")), seo_description: String(form.get("seo_description")),
      tags: String(form.get("tags")).split(",").map((tag) => tag.trim()).filter(Boolean),
      pinned_comment: String(form.get("pinned_comment")), chapters: String(form.get("chapters")), playlist: String(form.get("playlist")),
      next_video_cta: String(form.get("next_video_cta")), scores, rationale: String(form.get("rationale")),
    };
    try {
      await registerThumbnail(projectId, String(form.get("source_png")), aspect, label);
      const next = { candidates: [...(document?.candidates ?? []), candidate] };
      await savePackagingCandidates(projectId, next, (document?.candidates.length ?? 0) > 0);
      setDocument(next); setSaved(true); formElement.reset(); setScores(initialScores());
    } catch (error) { setSaveError(error instanceof Error ? error.message : "Could not save candidate"); }
  }

  const nextLabel = labels.find((label) => !document?.candidates.some((candidate) => candidate.label === label));
  return <section aria-labelledby="packaging-heading" className="packaging-panel">
    <h2 id="packaging-heading">Packaging Lab</h2>
    <p>Scores are advisory guidance, not objective truth. Nothing here changes YouTube automatically.</p>
    {loadError ? <p role="alert">Could not load packaging candidates: {loadError}</p> : !document ? <p>Loading packaging candidates…</p> : document.candidates.length === 0 ? <p>No packaging candidates saved for this project yet.</p> : <div className="packaging-grid">{document.candidates.map((candidate) => <CandidateCard key={candidate.label} candidate={candidate} />)}</div>}
    {document && nextLabel && <form className="packaging-form" onSubmit={submit}>
      <h3>Register a local title + thumbnail pair</h3>
      <label>Candidate label<select name="label" defaultValue={nextLabel}>{labels.filter((label) => !document.candidates.some((candidate) => candidate.label === label)).map((label) => <option key={label}>{label}</option>)}</select></label>
      <label>Thumbnail aspect<select name="aspect" defaultValue="16:9"><option>16:9</option><option>9:16</option></select></label>
      <label>Title candidate<input name="title" required /></label><label>Approved PNG path<input name="source_png" required /></label>
      <label>Hook<textarea name="hook" required /></label><label>SEO description<textarea name="seo_description" required /></label>
      <label>Tags<input name="tags" placeholder="Namibia, Skeleton Coast" required /></label><label>Pinned comment<textarea name="pinned_comment" required /></label>
      <label>Chapters<textarea name="chapters" required /></label><label>Playlist<input name="playlist" required /></label><label>Next-video CTA<textarea name="next_video_cta" required /></label>
      <fieldset><legend>Advisory scores</legend>{criteria.map(([key, label]) => <label key={key}>{label}<input aria-label={`${label} advisory score`} type="number" min="0" max="100" value={scores[key]} onChange={(event) => setScores({ ...scores, [key]: Number(event.target.value) })} required /></label>)}</fieldset>
      <label>Plain-language rationale<textarea name="rationale" required /></label><button type="submit">Save local candidate</button>
      {saveError && <p role="alert">Could not save candidate: {saveError}</p>}{saved && <p role="status">Candidate saved inside this project. Review it before making any YouTube change.</p>}
    </form>}
  </section>;
}
