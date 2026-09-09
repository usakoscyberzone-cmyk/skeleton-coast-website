"""Metric normalization and persistence helpers for read-only YouTube data."""

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
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
    ctr = _bounded_float(raw.get("ctr"), maximum=1)
    if raw.get("ctr") is not None and ctr is None and _is_finite_number(raw.get("ctr")):
        raise ValueError("CTR must be a normalized ratio between 0 and 1")
    supplied_raw = raw.get("traffic_raw")
    traffic = supplied_raw or raw.get("traffic") or {}
    live_traffic = bool(supplied_raw) or any(key in traffic for key in ("RELATED_VIDEO", "YT_SEARCH", "EXT_URL"))
    views = _nonnegative_int(raw.get("views"))
    subscribers_gained = _nonnegative_int(raw.get("subscribers_gained"))
    retention = raw.get("retention")
    return MetricSnapshotInput(
        youtube_video_id=str(raw["video_id"]),
        channel_id=str(raw["channel_id"]) if raw.get("channel_id") else None,
        views=views,
        impressions=_nonnegative_int(raw.get("impressions")),
        ctr=ctr,
        watch_minutes=_nonnegative_float(raw.get("watch_minutes")),
        avg_view_duration_seconds=_nonnegative_float(raw.get("avg_view_duration_seconds")),
        average_percentage_viewed=_percent_to_ratio(raw.get("average_percentage_viewed")),
        subscribers_gained=subscribers_gained,
        subscriber_conversion_rate=(
            subscribers_gained / views
            if subscribers_gained is not None and views is not None and 0 <= subscribers_gained <= views and views > 0
            else None
        ),
        browse_share=_traffic_share(traffic, "BROWSE") if live_traffic else _normalized_share(traffic, "BROWSE"),
        suggested_share=_traffic_share(traffic, "RELATED_VIDEO") if live_traffic else _normalized_share(traffic, "SUGGESTED"),
        search_share=_traffic_share(traffic, "YT_SEARCH") if live_traffic else _normalized_share(traffic, "SEARCH"),
        external_share=_traffic_share(traffic, "EXT_URL") if live_traffic else _normalized_share(traffic, "EXTERNAL"),
        shorts_feed_share=_traffic_share(traffic, "SHORTS") if live_traffic else _normalized_share(traffic, "SHORTS"),
        returning_viewers=_nonnegative_int(raw.get("returning_viewers")),
        retention=_normalize_retention(retention),
        views_1h=_nonnegative_int(raw.get("views_1h")),
        views_24h=_nonnegative_int(raw.get("views_24h")),
        views_7d=_nonnegative_int(raw.get("views_7d")),
        title=raw.get("title"),
        duration_seconds=_nonnegative_int(raw.get("duration_seconds")),
        length_seconds=_nonnegative_int(raw.get("length_seconds", raw.get("duration_seconds"))),
        video_type=raw.get("video_type"),
        format=raw.get("format", raw.get("video_type")),
        topic=raw.get("topic"),
        published_at=raw.get("published_at"),
    )


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _nonnegative_int(value: Any) -> int | None:
    if not _is_finite_number(value):
        return None
    number = float(value)
    return int(number) if number >= 0 and number.is_integer() else None


def _nonnegative_float(value: Any) -> float | None:
    if not _is_finite_number(value):
        return None
    number = float(value)
    return number if number >= 0 else None


def _bounded_float(value: Any, *, minimum: float = 0, maximum: float) -> float | None:
    if not _is_finite_number(value):
        return None
    number = float(value)
    return number if minimum <= number <= maximum else None


def _as_ratio(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number < 0:
        return None
    return round(number / 100, 6) if number > 1 else number


def _percent_to_ratio(value: Any) -> float | None:
    percentage = _bounded_float(value, maximum=100)
    return percentage / 100 if percentage is not None else None


def _traffic_share(traffic: dict[str, Any], source: str) -> float | None:
    if source not in traffic:
        return None
    values = [_nonnegative_float(value) for value in traffic.values()]
    source_value = _nonnegative_float(traffic[source])
    if source_value is None or any(value is None for value in values):
        return None
    total = sum(values)
    share = source_value / total if total > 0 else None
    return share if share is None or math.isfinite(share) else None


def _normalized_share(traffic: dict[str, Any], source: str) -> float | None:
    return _bounded_float(traffic.get(source), maximum=1) if source in traffic else None


def _normalize_retention(points: Any) -> list[dict[str, float]] | None:
    if not isinstance(points, list) or not points:
        return None
    normalized = []
    for point in points:
        if not isinstance(point, dict):
            return None
        elapsed = _bounded_float(point.get("elapsed_ratio"), maximum=1)
        audience = _nonnegative_float(
            point.get("audienceWatchRatio", point.get("audience_retention"))
        )
        if elapsed is None or audience is None:
            return None
        normalized.append({"elapsed_ratio": elapsed, "audience_retention": audience})
    return normalized


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
    if existing is not None and existing.channel_id != metric.channel_id:
        raise ValueError("A metric snapshot's channel provenance is immutable")
    update_values = dict(values)
    update_values.pop("channel_id")
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
