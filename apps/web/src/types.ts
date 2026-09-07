export type RecommendationState = "green" | "amber" | "red";

export interface ProjectSummary { id: number; name: string; path: string; }
export interface MediaFile {
  id: number; path: string; kind: string; duration_seconds: number | null;
  width: number | null; height: number | null; frame_rate: number | null;
  codec: string | null; probe_error: string | null;
}
export interface ProjectDetail extends ProjectSummary { media_files: MediaFile[]; }
export interface MetricTotal { value: number | null; coverage: number; }
export interface VideoSummary { title: string; views: number | null; }
export interface VideoState { title: string; state: RecommendationState; }
export interface DashboardSummary {
  video_count: number;
  views: MetricTotal;
  watch_minutes: MetricTotal;
  subscribers_gained: MetricTotal;
  realtime_views?: number | null;
  top_long_form?: VideoSummary | null;
  top_short?: VideoSummary | null;
  traffic_sources?: Record<string, number>;
  video_states?: VideoState[];
}
export interface Recommendation {
  id: number; youtube_video_id: string; state: RecommendationState; action: string;
  reason: string; confidence: "low" | "medium" | "high"; data_used: Record<string, unknown>;
}
export interface YouTubeStatus { status: string; detail?: string; channel_title?: string; channel_id?: string; }
