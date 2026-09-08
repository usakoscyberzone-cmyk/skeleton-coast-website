import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getProject, getShortPlans } from "../api/client";
import { ShortsFunnelPanel } from "../components/ShortsFunnelPanel";
import { PackagingPanel } from "../components/PackagingPanel";
import type { MediaFile, ProjectDetail, ShortPlan } from "../types";

const value = (candidate: string | number | null) => candidate == null ? "Unavailable" : candidate;
function MediaRow({ media }: { media: MediaFile }) { return <article className="media-row"><h3>{media.path.split(/[\\/]/).pop()}</h3><dl><div><dt>Type</dt><dd>{media.kind}</dd></div><div><dt>Duration</dt><dd>{value(media.duration_seconds)}</dd></div><div><dt>Resolution</dt><dd>{media.width == null || media.height == null ? "Unavailable" : `${media.width} × ${media.height}`}</dd></div><div><dt>Frame rate</dt><dd>{value(media.frame_rate)}</dd></div><div><dt>Codec</dt><dd>{value(media.codec)}</dd></div></dl>{media.probe_error && <p className="probe-error">Probe error: {media.probe_error}</p>}</article>; }
export function ProjectDetailPage() {
  const { id } = useParams(); const [project, setProject] = useState<ProjectDetail | null>(null); const [error, setError] = useState<string | null>(null); const [plans, setPlans] = useState<ShortPlan[] | null>(null); const [plansError, setPlansError] = useState<string | null>(null);
  useEffect(() => { if (!id) { setError("Project identifier is missing."); return; } getProject(id).then(setProject).catch((reason: Error) => setError(reason.message)); getShortPlans(id).then(setPlans).catch((reason: Error) => setPlansError(reason.message)); }, [id]);
  if (error) return <main><p role="alert">Could not load project: {error}</p></main>;
  if (!project) return <main><p>Loading project…</p></main>;
  return <main><header className="page-header"><div><p className="eyebrow">Discovered local project</p><h1>{project.name}</h1></div><p className="path">{project.path}</p></header><section><h2>Long-form project context</h2><h3>Indexed media</h3>{project.media_files.length === 0 ? <p>No media files have been indexed for this project yet.</p> : <div className="media-list">{project.media_files.map((media) => <MediaRow key={media.id} media={media} />)}</div>}</section><PackagingPanel projectId={id!} /><ShortsFunnelPanel plans={plans} error={plansError} /></main>;
}
