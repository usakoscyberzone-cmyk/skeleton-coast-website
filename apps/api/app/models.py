from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .db import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (UniqueConstraint("project_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTC datetime must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


class VideoMetricSnapshot(Base):
    __tablename__ = "video_metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    analytics_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    analytics_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    length_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    watch_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_view_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_percentage_viewed: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscribers_gained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscriber_conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    browse_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    external_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    shorts_feed_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    returning_viewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    views_1h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views_7d: Mapped[int | None] = mapped_column(Integer, nullable=True)


Index(
    "uq_video_metric_period",
    VideoMetricSnapshot.youtube_video_id,
    func.coalesce(VideoMetricSnapshot.analytics_start_date, ""),
    func.coalesce(VideoMetricSnapshot.analytics_end_date, ""),
    unique=True,
)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    data_used_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShortPlan(Base):
    __tablename__ = "short_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    hook_type: Mapped[str] = mapped_column(String(64))
    source_start_seconds: Mapped[float] = mapped_column(Float)
    source_end_seconds: Mapped[float] = mapped_column(Float)
    target_duration_seconds: Mapped[float] = mapped_column(Float)
    on_screen_text: Mapped[str] = mapped_column(Text)
    cta: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planned")
    strategic_role: Mapped[str | None] = mapped_column(String(32), nullable=True)


class LearningPattern(Base):
    __tablename__ = "learning_patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), index=True)
    pattern_type: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
