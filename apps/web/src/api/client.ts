import type { DashboardSummary, ProjectDetail, ProjectSummary, Recommendation, YouTubeStatus } from "../types";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail ?? message; } catch { /* use status message */ }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export function getProjects(): Promise<ProjectSummary[]> { return getJson("/projects"); }
export function getProject(id: string | number): Promise<ProjectDetail> { return getJson(`/projects/${id}`); }
export function getDashboardSummary(): Promise<DashboardSummary> { return getJson("/analytics/summary"); }
export function getYouTubeStatus(): Promise<YouTubeStatus> { return getJson("/youtube/status"); }
export async function getActiveRecommendations(): Promise<Recommendation[]> {
  try { return await getJson("/recommendations/active"); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}
