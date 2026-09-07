import { Link } from "react-router-dom";
import type { ProjectSummary } from "../types";

export function ProjectCard({ project }: { project: ProjectSummary }) {
  return <article className="project-card"><p className="eyebrow">Discovered project</p><h2>{project.name}</h2><p className="path">{project.path}</p><Link to={`/projects/${project.id}`}>View project media</Link></article>;
}
