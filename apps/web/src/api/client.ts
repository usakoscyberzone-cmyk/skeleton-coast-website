import type { DashboardSummary, LearningPattern, MediaFile, PackagingCandidate, PackagingDocument, ProjectDetail, ProjectSummary, Recommendation, RetentionData, ShortPlan, ThumbnailRegistration, YouTubeStatus } from "../types";

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
function shortPlan(value: unknown, endpoint: string): ShortPlan {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.project_id !== "number" || typeof value.hook_type !== "string" || !validShortRange(value.source_start_seconds, value.source_end_seconds, value.target_duration_seconds) || typeof value.on_screen_text !== "string" || typeof value.cta !== "string" || !["planned", "ready", "published"].includes(String(value.status)) || !["discovery", "conversion", "winner"].includes(String(value.strategic_role))) return invalid(endpoint);
  return value as unknown as ShortPlan;
}
function validShortRange(start: unknown, end: unknown, target: unknown) { return typeof start === "number" && typeof end === "number" && typeof target === "number" && Number.isFinite(start) && Number.isFinite(end) && Number.isFinite(target) && start >= 0 && end > start && target > 0 && target <= end - start; }
function dashboard(value: unknown): DashboardSummary {
  const metricFields = ["views", "watch_minutes", "subscribers_gained", "impressions", "ctr", "avg_view_duration_seconds", "average_percentage_viewed", "subscriber_conversion_rate", "returning_viewers", "views_1h", "views_24h", "views_7d"] as const;
  const required = ["views", "watch_minutes", "subscribers_gained"] as const;
  if (!isRecord(value) || typeof value.video_count !== "number" || required.some((field) => !metric(value[field])) || metricFields.some((field) => value[field] !== undefined && !metric(value[field])) || !video(value.top_long_form) || !video(value.top_short) || !isRecord(value.traffic_sources) || Object.values(value.traffic_sources).some((share) => typeof share !== "number") || (value.traffic_source_coverage !== undefined && (!isRecord(value.traffic_source_coverage) || Object.values(value.traffic_source_coverage).some((coverage) => typeof coverage !== "number"))) || (value.videos !== undefined && (!Array.isArray(value.videos) || value.videos.some((item) => !video(item)))) || (value.retention_videos !== undefined && (!Array.isArray(value.retention_videos) || value.retention_videos.some((item) => !isRecord(item) || typeof item.id !== "string" || typeof item.title !== "string"))) || (value.topics !== undefined && (!isRecord(value.topics) || Object.values(value.topics).some((item) => !metric(item)))) || !(value.realtime_views === undefined || numberOrNull(value.realtime_views))) return invalid("/analytics/summary");
  const unavailable = { value: null, coverage: 0 };
  return { ...value, ...Object.fromEntries(metricFields.map((field) => [field, value[field] ?? unavailable])), traffic_source_coverage: value.traffic_source_coverage ?? {}, videos: value.videos ?? [], retention_videos: value.retention_videos ?? [], topics: value.topics ?? {} } as DashboardSummary;
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

async function sendJson<T>(path: string, method: "POST" | "PUT", body: unknown, validate: (value: unknown) => T): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { method, headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail ?? message; } catch { /* use status message */ }
    throw new ApiError(response.status, message);
  }
  return validate(await response.json());
}

const scoreFields = ["curiosity", "clarity", "search_relevance", "audience_fit", "uniqueness", "title_thumbnail_complementarity"] as const;
function packagingCandidate(value: unknown): PackagingCandidate {
  const textFields = ["title", "hook", "seo_description", "pinned_comment", "chapters", "playlist", "next_video_cta", "rationale"] as const;
  if (!isRecord(value) || !["A", "B", "C"].includes(String(value.label)) || textFields.some((field) => typeof value[field] !== "string" || !(value[field] as string).trim()) || !Array.isArray(value.tags) || value.tags.length === 0 || value.tags.some((tag) => typeof tag !== "string" || !tag.trim()) || !isRecord(value.thumbnail) || !["16:9", "9:16"].includes(String(value.thumbnail.aspect)) || typeof value.thumbnail.file !== "string" || !isRecord(value.scores)) return invalid("/projects/:id/assets/packaging");
  const scores = value.scores;
  if (scoreFields.some((field) => !Number.isInteger(scores[field]) || (scores[field] as number) < 0 || (scores[field] as number) > 100)) return invalid("/projects/:id/assets/packaging");
  const suffix = value.thumbnail.aspect === "16:9" ? "16x9" : "9x16";
  if (value.thumbnail.file !== `Thumbnails/thumbnail-${value.label}-${suffix}.png`) return invalid("/projects/:id/assets/packaging");
  return value as unknown as PackagingCandidate;
}

export function getProjects(): Promise<ProjectSummary[]> { return getJson("/projects", (value) => Array.isArray(value) ? value.map((item) => project(item, "/projects")) : invalid("/projects")); }
export function getProject(id: string | number): Promise<ProjectDetail> { return getJson(`/projects/${id}`, (value) => { const base = project(value, `/projects/${id}`); if (!isRecord(value) || !Array.isArray(value.media_files)) return invalid(`/projects/${id}`); return { ...base, media_files: value.media_files.map((item) => mediaFile(item, `/projects/${id}`)) }; }); }
export function getShortPlans(projectId: string | number): Promise<ShortPlan[]> { return getJson(`/projects/${projectId}/shorts`, (value) => Array.isArray(value) ? value.map((item) => shortPlan(item, `/projects/${projectId}/shorts`)) : invalid(`/projects/${projectId}/shorts`)); }
export function getPackagingCandidates(projectId: string | number): Promise<PackagingDocument> { return getJson(`/projects/${projectId}/assets/packaging`, (value) => { if (!isRecord(value) || !Array.isArray(value.candidates) || value.candidates.length > 3 || typeof value.revision !== "string" || !/^(missing|[0-9a-f]{64})$/.test(value.revision)) return invalid("/projects/:id/assets/packaging"); const candidates = value.candidates.map(packagingCandidate); if (new Set(candidates.map((candidate) => candidate.label)).size !== candidates.length) return invalid("/projects/:id/assets/packaging"); return { candidates, revision: value.revision }; }); }
export function savePackagingCandidates(projectId: string | number, document: PackagingDocument, thumbnail_registration: ThumbnailRegistration): Promise<{ file: string; revision: string }> { return sendJson(`/projects/${projectId}/assets/packaging`, "PUT", { candidates: document.candidates, expected_revision: document.revision, thumbnail_registration }, (value) => isRecord(value) && typeof value.file === "string" && typeof value.revision === "string" ? { file: value.file, revision: value.revision } : invalid("/projects/:id/assets/packaging")); }
export function getDashboardSummary(): Promise<DashboardSummary> { return getJson("/analytics/summary", dashboard); }
export function getRetention(videoId: string): Promise<RetentionData> { return getJson(`/analytics/videos/${encodeURIComponent(videoId)}/retention`, (value) => isRecord(value) && typeof value.video_id === "string" && (value.retention === null || (Array.isArray(value.retention) && value.retention.every((point) => isRecord(point) && typeof point.elapsed_ratio === "number" && typeof point.audience_retention === "number"))) ? value as unknown as RetentionData : invalid("/analytics/videos/:id/retention")); }
export async function getLearningPatterns(): Promise<LearningPattern[]> {
  try { return await getJson("/learning/patterns", (value) => Array.isArray(value) && value.every((item) => isRecord(item) && typeof item.id === "number" && typeof item.topic === "string" && typeof item.pattern_type === "string" && typeof item.summary === "string" && typeof item.confidence === "string" && typeof item.evidence_count === "number") ? value as LearningPattern[] : invalid("/learning/patterns")); }
  catch (error) { if (error instanceof ApiError && error.status === 404) return []; throw error; }
}
export function getYouTubeStatus(): Promise<YouTubeStatus> { return getJson("/youtube/status", (value) => { if (!isRecord(value) || typeof value.status !== "string" || !stringOrUndefined(value.detail) || !stringOrUndefined(value.channel_title) || !stringOrUndefined(value.channel_id)) return invalid("/youtube/status"); return { status: value.status, detail: value.detail as string | undefined, channel_title: value.channel_title as string | undefined, channel_id: value.channel_id as string | undefined }; }); }
export async function getActiveRecommendations(): Promise<Recommendation[]> {
  try { return await getJson("/recommendations/active", (value) => Array.isArray(value) ? value.map(recommendation) : invalid("/recommendations/active")); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}
