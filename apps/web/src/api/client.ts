import type { DashboardSummary, MediaFile, ProjectDetail, ProjectSummary, Recommendation, YouTubeStatus } from "../types";

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

type UnknownRecord = Record<string, unknown>;
const isRecord = (value: unknown): value is UnknownRecord => typeof value === "object" && value !== null && !Array.isArray(value);
const invalid = (endpoint: string): never => { throw new Error(`Invalid API response from ${endpoint}`); };
const numberOrNull = (value: unknown) => typeof value === "number" || value === null;
const stringOrUndefined = (value: unknown) => value === undefined || typeof value === "string";
const stringOrNull = (value: unknown) => typeof value === "string" || value === null;
function project(value: unknown, endpoint: string): ProjectSummary {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.name !== "string" || typeof value.path !== "string") return invalid(endpoint);
  return { id: value.id as number, name: value.name as string, path: value.path as string };
}
function mediaFile(value: unknown, endpoint: string): MediaFile {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.path !== "string" || typeof value.kind !== "string" || !numberOrNull(value.duration_seconds) || !numberOrNull(value.width) || !numberOrNull(value.height) || !numberOrNull(value.frame_rate) || !stringOrNull(value.codec) || !stringOrNull(value.probe_error)) return invalid(endpoint);
  return { id: value.id as number, path: value.path as string, kind: value.kind as string, duration_seconds: value.duration_seconds as number | null, width: value.width as number | null, height: value.height as number | null, frame_rate: value.frame_rate as number | null, codec: value.codec as string | null, probe_error: value.probe_error as string | null };
}
function dashboard(value: unknown): DashboardSummary {
  if (!isRecord(value) || typeof value.video_count !== "number" || !metric(value.views) || !metric(value.watch_minutes) || !metric(value.subscribers_gained) || !video(value.top_long_form) || !video(value.top_short) || !isRecord(value.traffic_sources) || Object.values(value.traffic_sources).some((share) => typeof share !== "number") || !(value.realtime_views === undefined || numberOrNull(value.realtime_views))) return invalid("/analytics/summary");
  return { video_count: value.video_count as number, views: value.views as DashboardSummary["views"], watch_minutes: value.watch_minutes as DashboardSummary["watch_minutes"], subscribers_gained: value.subscribers_gained as DashboardSummary["subscribers_gained"], realtime_views: value.realtime_views as number | null | undefined, top_long_form: value.top_long_form as DashboardSummary["top_long_form"], top_short: value.top_short as DashboardSummary["top_short"], traffic_sources: value.traffic_sources as Record<string, number> };
}
function metric(value: unknown) { return isRecord(value) && numberOrNull(value.value) && typeof value.coverage === "number"; }
function video(value: unknown) { return value === null || (isRecord(value) && typeof value.id === "string" && typeof value.title === "string" && typeof value.views === "number"); }
function recommendation(value: unknown): Recommendation {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.youtube_video_id !== "string" || !["green", "amber", "red"].includes(String(value.state)) || typeof value.action !== "string" || typeof value.reason !== "string" || !["low", "medium", "high"].includes(String(value.confidence)) || !isRecord(value.data_used)) return invalid("/recommendations/active");
  return { id: value.id as number, youtube_video_id: value.youtube_video_id as string, state: value.state as Recommendation["state"], action: value.action as string, reason: value.reason as string, confidence: value.confidence as Recommendation["confidence"], data_used: value.data_used as Record<string, unknown> };
}

async function getJson<T>(path: string, validate: (value: unknown) => T): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail ?? message; } catch { /* use status message */ }
    throw new ApiError(response.status, message);
  }
  return validate(await response.json());
}

export function getProjects(): Promise<ProjectSummary[]> { return getJson("/projects", (value) => Array.isArray(value) ? value.map((item) => project(item, "/projects")) : invalid("/projects")); }
export function getProject(id: string | number): Promise<ProjectDetail> { return getJson(`/projects/${id}`, (value) => { const base = project(value, `/projects/${id}`); if (!isRecord(value) || !Array.isArray(value.media_files)) return invalid(`/projects/${id}`); return { ...base, media_files: value.media_files.map((item) => mediaFile(item, `/projects/${id}`)) }; }); }
export function getDashboardSummary(): Promise<DashboardSummary> { return getJson("/analytics/summary", dashboard); }
export function getYouTubeStatus(): Promise<YouTubeStatus> { return getJson("/youtube/status", (value) => { if (!isRecord(value) || typeof value.status !== "string" || !stringOrUndefined(value.detail) || !stringOrUndefined(value.channel_title) || !stringOrUndefined(value.channel_id)) return invalid("/youtube/status"); return { status: value.status, detail: value.detail as string | undefined, channel_title: value.channel_title as string | undefined, channel_id: value.channel_id as string | undefined }; }); }
export async function getActiveRecommendations(): Promise<Recommendation[]> {
  try { return await getJson("/recommendations/active", (value) => Array.isArray(value) ? value.map(recommendation) : invalid("/recommendations/active")); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}
