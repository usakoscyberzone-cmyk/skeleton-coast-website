export type RecommendationState = "green" | "amber" | "red";

export interface ProjectSummary { id: number; name: string; path: string; }
export interface MediaFile {
  id: number; path: string; kind: string; duration_seconds: number | null;
  width: number | null; height: number | null; frame_rate: number | null;
  codec: string | null; probe_error: string | null;
}
export interface ProjectDetail extends ProjectSummary { media_files: MediaFile[]; }
export type ShortStatus = "planned" | "ready" | "published";
export type ShortRole = "discovery" | "conversion" | "winner";
export interface ShortPlan {
  id: number; project_id: number; hook_type: string; source_start_seconds: number;
  source_end_seconds: number; target_duration_seconds: number; on_screen_text: string;
  cta: string; status: ShortStatus; strategic_role: ShortRole;
}
export interface MetricTotal { value: number | null; coverage: number; }
export interface VideoSummary { id: string; title: string; views: number; }
export interface RetentionVideo { id: string; title: string; }
export interface RetentionPoint { elapsed_ratio: number; audience_retention: number; }
export interface DashboardSummary {
  video_count: number;
  views: MetricTotal;
  watch_minutes: MetricTotal;
  subscribers_gained: MetricTotal;
  realtime_views?: number | null;
  top_long_form: VideoSummary | null;
  top_short: VideoSummary | null;
  traffic_sources: Record<string, number>;
  impressions: MetricTotal; ctr: MetricTotal; avg_view_duration_seconds: MetricTotal;
  average_percentage_viewed: MetricTotal; subscriber_conversion_rate: MetricTotal;
  returning_viewers: MetricTotal; views_1h: MetricTotal; views_24h: MetricTotal; views_7d: MetricTotal;
  traffic_source_coverage: Record<string, number>; videos: VideoSummary[]; retention_videos: RetentionVideo[]; topics: Record<string, MetricTotal>;
}
export interface Recommendation {
  id: number; youtube_video_id: string; state: RecommendationState; action: string;
  reason: string; confidence: "low" | "medium" | "high"; data_used: Record<string, unknown>;
}
export interface YouTubeStatus { status: string; detail?: string; channel_title?: string; channel_id?: string; }
export interface RetentionData { video_id: string; retention: RetentionPoint[] | null; }
export interface LearningPattern { id: number; topic: string; pattern_type: string; summary: string; confidence: string; evidence_count: number; }
