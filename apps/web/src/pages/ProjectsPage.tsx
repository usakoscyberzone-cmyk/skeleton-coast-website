import { useEffect, useState } from "react";
import { getProjects } from "../api/client";
import { ProjectCard } from "../components/ProjectCard";
import type { ProjectSummary } from "../types";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getProjects().then(setProjects).catch((reason: Error) => setError(reason.message)); }, []);
  return <main><header className="page-header"><div><p className="eyebrow">Windows helper discovery</p><h1>Projects</h1></div><p>Direct children of I:\YouTube Projects</p></header>
    {error && <p role="alert">Could not load projects: {error}</p>}
    {projects === null && !error && <p>Loading projects…</p>}
    {projects?.length === 0 && <p>No projects have been discovered. Run the Windows helper scan; Resolve projects are never scanned or changed by this browser.</p>}
    {projects && projects.length > 0 && <section className="project-grid">{projects.map((project) => <ProjectCard key={project.id} project={project} />)}</section>}
  </main>;
}
