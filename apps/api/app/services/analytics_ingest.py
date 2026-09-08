"""Metric normalization and persistence helpers for read-only YouTube data."""

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Any
from dataclasses import asdict, is_dataclass

from sqlalchemy import case, func, select
from sqlalchemy import literal_column
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import VideoMetricSnapshot
from .youtube_client import RawVideoMetrics


@dataclass(frozen=True)
class MetricSnapshotInput:
    youtube_video_id: str
    channel_id: str | None = None
    views: int | None = None
    impressions: int | None = None
    ctr: float | None = None
    watch_minutes: float | None = None
    avg_view_duration_seconds: float | None = None
    average_percentage_viewed: float | None = None
    subscribers_gained: int | None = None
    subscriber_conversion_rate: float | None = None
    browse_share: float | None = None
    suggested_share: float | None = None
    search_share: float | None = None
    external_share: float | None = None
    shorts_feed_share: float | None = None
    returning_viewers: int | None = None
    retention: list[dict[str, float]] | None = None
    views_1h: int | None = None
    views_24h: int | None = None
    views_7d: int | None = None
    title: str | None = None
    duration_seconds: int | None = None
    length_seconds: int | None = None
    video_type: str | None = None
    format: str | None = None
    topic: str | None = None
    published_at: datetime | None = None


def normalize_metrics(raw: RawVideoMetrics | dict[str, object]) -> MetricSnapshotInput:
    """Convert API units to one internal convention: ratios are 0..1, gaps are None."""
    if is_dataclass(raw):
        raw = asdict(raw)
    ctr = raw.get("ctr")
    if ctr is not None and not 0 <= float(ctr) <= 1:
        raise ValueError("CTR must be a normalized ratio between 0 and 1")
    supplied_raw = raw.get("traffic_raw")
    traffic = supplied_raw or raw.get("traffic") or {}
    live_traffic = bool(supplied_raw) or any(key in traffic for key in ("RELATED_VIDEO", "YT_SEARCH", "EXT_URL"))
    views = _as_int(raw.get("views"))
    subscribers_gained = _as_int(raw.get("subscribers_gained"))
    retention = raw.get("retention")
    return MetricSnapshotInput(
        youtube_video_id=str(raw["video_id"]),
        channel_id=str(raw["channel_id"]) if raw.get("channel_id") else None,
        views=views,
        impressions=_as_int(raw.get("impressions")),
        ctr=_as_float(ctr),
        watch_minutes=_as_float(raw.get("watch_minutes")),
        avg_view_duration_seconds=_as_float(raw.get("avg_view_duration_seconds")),
        average_percentage_viewed=_percent_to_ratio(raw.get("average_percentage_viewed")),
        subscribers_gained=subscribers_gained,
        subscriber_conversion_rate=(
            subscribers_gained / views
            if subscribers_gained is not None and views is not None and views > 0
            else None
        ),
        browse_share=_traffic_share(traffic, "BROWSE") if live_traffic else _normalized_share(traffic, "BROWSE"),
        suggested_share=_traffic_share(traffic, "RELATED_VIDEO") if live_traffic else _normalized_share(traffic, "SUGGESTED"),
        search_share=_traffic_share(traffic, "YT_SEARCH") if live_traffic else _normalized_share(traffic, "SEARCH"),
        external_share=_traffic_share(traffic, "EXT_URL") if live_traffic else _normalized_share(traffic, "EXTERNAL"),
        shorts_feed_share=_traffic_share(traffic, "SHORTS") if live_traffic else _normalized_share(traffic, "SHORTS"),
        returning_viewers=_as_int(raw.get("returning_viewers")),
        retention=_normalize_retention(retention),
        views_1h=_as_int(raw.get("views_1h")),
        views_24h=_as_int(raw.get("views_24h")),
        views_7d=_as_int(raw.get("views_7d")),
        title=raw.get("title"),
        duration_seconds=_as_int(raw.get("duration_seconds")),
        length_seconds=_as_int(raw.get("length_seconds", raw.get("duration_seconds"))),
        video_type=raw.get("video_type"),
        format=raw.get("format", raw.get("video_type")),
        topic=raw.get("topic"),
        published_at=raw.get("published_at"),
    )


def _as_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _as_ratio(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number < 0:
        return None
    return round(number / 100, 6) if number > 1 else number


def _percent_to_ratio(value: Any) -> float | None:
    return None if value is None else float(value) / 100


def _traffic_share(traffic: dict[str, Any], source: str) -> float | None:
    if source not in traffic:
        return None
    total = sum(float(value) for value in traffic.values())
    return float(traffic[source]) / total if total else None


def _normalized_share(traffic: dict[str, Any], source: str) -> float | None:
    return float(traffic[source]) if source in traffic else None


def _normalize_retention(points: Any) -> list[dict[str, float]] | None:
    if points is None:
        return None
    return [
        {
            "elapsed_ratio": float(point["elapsed_ratio"]),
            "audience_retention": float(point.get("audienceWatchRatio", point.get("audience_retention"))),
        }
        for point in points
    ]


def persist_metric_snapshot(
    session: Session, metric: MetricSnapshotInput, *, start_date: date, end_date: date
) -> VideoMetricSnapshot:
    """Upsert a retry-safe snapshot for one video and reporting period."""
    values = {
        name: getattr(metric, name)
        for name in MetricSnapshotInput.__dataclass_fields__
        if name != "youtube_video_id" and name != "retention"
    }
    values["retention_json"] = json.dumps(metric.retention) if metric.retention is not None else None
    statement = sqlite_insert(VideoMetricSnapshot).values(youtube_video_id=metric.youtube_video_id, analytics_start_date=start_date, analytics_end_date=end_date, **values)
    existing = session.scalar(select(VideoMetricSnapshot).where(
        VideoMetricSnapshot.youtube_video_id == metric.youtube_video_id,
        VideoMetricSnapshot.analytics_start_date == start_date,
        VideoMetricSnapshot.analytics_end_date == end_date,
    ))
    if existing is not None and existing.channel_id and metric.channel_id and existing.channel_id != metric.channel_id:
        raise ValueError("A metric snapshot's channel provenance is immutable")
    update_values = dict(values)
    update_values["channel_id"] = func.coalesce(VideoMetricSnapshot.channel_id, statement.excluded.channel_id)
    update_values["topic"] = func.coalesce(statement.excluded.topic, VideoMetricSnapshot.topic)
    update_values["ctr"] = func.coalesce(statement.excluded.ctr, VideoMetricSnapshot.ctr)
    update_values["format"] = case(
        (statement.excluded.format.in_(("long", "short", "live")), statement.excluded.format),
        else_=VideoMetricSnapshot.format,
    )
    session.execute(statement.on_conflict_do_update(index_elements=[VideoMetricSnapshot.youtube_video_id, literal_column("coalesce(analytics_start_date, '')"), literal_column("coalesce(analytics_end_date, '')")], set_=update_values))
    snapshot = session.scalar(select(VideoMetricSnapshot).where(VideoMetricSnapshot.youtube_video_id == metric.youtube_video_id, VideoMetricSnapshot.analytics_start_date.is_(start_date) if start_date is None else VideoMetricSnapshot.analytics_start_date == start_date, VideoMetricSnapshot.analytics_end_date.is_(end_date) if end_date is None else VideoMetricSnapshot.analytics_end_date == end_date))
    session.flush()
    return snapshot
