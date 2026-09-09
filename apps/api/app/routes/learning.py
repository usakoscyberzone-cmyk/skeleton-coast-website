"""Read-only learning library rebuilt from locally persisted channel evidence."""

import json
import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import begin_immediate_transaction, get_session
from ..models import LearningPattern, VideoMetricSnapshot
from ..services.learning_library import PATTERN_TYPES, ChannelDataset, ChannelVideo, extract_learning_patterns


router = APIRouter(prefix="/learning", tags=["learning"])


class LearningMetadataUpdate(BaseModel):
    topic: str | None = Field(default=None, max_length=64)
    format: str | None = Field(default=None, max_length=32)
    thumbnail_wording: str | None = Field(default=None, max_length=64)
    hook_type: str | None = Field(default=None, max_length=64)
    geography: str | None = Field(default=None, max_length=64)
    is_follow_up: bool | None = None
    ctr: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    views_7d: int | None = Field(default=None, ge=0)

    @field_validator("topic")
    @classmethod
    def recognized_topic(cls, value: str | None) -> str | None:
        recognized = {name.casefold(): name for name in ("Fishing", "Namibia travel", "Angola", "History", "4x4", "Current events")}
        if value is None:
            return None
        if value.strip().casefold() not in recognized:
            raise ValueError("topic must be a recognized V1 topic")
        return recognized[value.strip().casefold()]

    @field_validator("format")
    @classmethod
    def recognized_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if normalized not in {"long", "short", "live"}:
            raise ValueError("format must be long, short, or live")
        return normalized

    @field_validator("thumbnail_wording", "hook_type", "geography")
    @classmethod
    def non_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("learning metadata text must not be blank")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def has_an_explicit_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one learning metadata field is required")
        return self


@router.put("/videos/{video_id}/metadata")
def update_learning_metadata(
    video_id: str,
    payload: LearningMetadataUpdate,
    session: Session = Depends(get_session),
) -> dict[str, int]:
    channel_id = get_settings().expected_youtube_channel_id
    if not channel_id:
        raise HTTPException(status_code=503, detail="EXPECTED_YOUTUBE_CHANNEL_ID is required.")
    begin_immediate_transaction(session)
    try:
        rows = list(session.scalars(select(VideoMetricSnapshot).where(
            VideoMetricSnapshot.youtube_video_id == video_id,
            VideoMetricSnapshot.channel_id == channel_id,
        )))
        if not rows:
            session.rollback()
            raise HTTPException(status_code=404, detail="Video metrics were not found for the configured channel.")
        latest = max(rows, key=_snapshot_rank)
        updates = payload.model_dump(exclude_unset=True)
        for name, value in updates.items():
            setattr(latest, name, value)
        session.commit()
        return {"updated": 1}
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise


@router.post("/rebuild")
def rebuild_learning_library(session: Session = Depends(get_session)) -> dict[str, int]:
    channel_id = get_settings().expected_youtube_channel_id
    if not channel_id:
        raise HTTPException(
            status_code=503,
            detail="EXPECTED_YOUTUBE_CHANNEL_ID must identify the single V1 channel before learning patterns can be rebuilt.",
        )
    dataset = ChannelDataset(channel_id=channel_id, videos=[_channel_video(row) for row in _latest_snapshots(session, channel_id)])
    patterns = extract_learning_patterns(dataset)
    begin_immediate_transaction(session)
    try:
        session.execute(delete(LearningPattern))
        for pattern in patterns:
            session.add(LearningPattern(
                topic=pattern.topic,
                pattern_type=pattern.pattern_type,
                summary=pattern.summary,
                evidence_json=json.dumps(pattern.evidence, sort_keys=True, separators=(",", ":")),
                confidence=pattern.confidence,
            ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"rebuilt": len(patterns)}


@router.get("/patterns")
def learning_patterns(session: Session = Depends(get_session)) -> list[dict]:
    channel_id = get_settings().expected_youtube_channel_id
    if not channel_id:
        return []
    rows = session.scalars(select(LearningPattern).order_by(LearningPattern.pattern_type, LearningPattern.topic, LearningPattern.id))
    result = []
    for row in rows:
        try:
            evidence = json.loads(row.evidence_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            row.pattern_type not in PATTERN_TYPES
            or row.confidence not in {"medium", "high"}
            or not row.topic.strip()
            or not row.summary.strip()
            or not _valid_evidence(evidence, channel_id)
        ):
            continue
        result.append({
            "id": row.id,
            "topic": row.topic,
            "pattern_type": row.pattern_type,
            "summary": row.summary,
            "confidence": row.confidence,
            "evidence_count": evidence["sample_count"],
            "evidence": evidence,
        })
    return result


def _latest_snapshots(session: Session, channel_id: str) -> list[VideoMetricSnapshot]:
    latest: dict[str, VideoMetricSnapshot] = {}
    for row in session.scalars(select(VideoMetricSnapshot).where(VideoMetricSnapshot.channel_id == channel_id)):
        current = latest.get(row.youtube_video_id)
        if current is None or _snapshot_rank(row) > _snapshot_rank(current):
            latest[row.youtube_video_id] = row
    return [latest[key] for key in sorted(latest)]


def _snapshot_rank(row: VideoMetricSnapshot) -> tuple[int, object, object, int]:
    valid_period = (
        row.analytics_start_date is not None and row.analytics_end_date is not None
        and row.analytics_start_date <= row.analytics_end_date
    )
    return (
        1 if valid_period else 0,
        row.analytics_end_date if valid_period else date.min,
        row.captured_at,
        row.id,
    )


def _channel_video(row: VideoMetricSnapshot) -> ChannelVideo:
    return ChannelVideo(
        video_id=row.youtube_video_id,
        topic=row.topic,
        format=row.format or row.video_type,
        length_seconds=row.length_seconds if row.length_seconds is not None else row.duration_seconds,
        views=row.views,
        views_7d=row.views_7d,
        ctr=row.ctr,
        average_percentage_viewed=row.average_percentage_viewed,
        subscriber_conversion_rate=row.subscriber_conversion_rate,
        browse_share=row.browse_share,
        suggested_share=row.suggested_share,
        thumbnail_wording=row.thumbnail_wording,
        hook_type=row.hook_type,
        geography=row.geography,
        is_follow_up=row.is_follow_up,
        comparison_period=(
            f"{row.analytics_start_date.isoformat()}/{row.analytics_end_date.isoformat()}"
            if row.analytics_start_date is not None and row.analytics_end_date is not None
            and row.analytics_start_date <= row.analytics_end_date
            else None
        ),
    )


def _valid_evidence(value: object, channel_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    count = value.get("sample_count")
    comparison_count = value.get("comparison_sample_count")
    required_text = ("metric", "winning_group", "comparison_group", "topic_scope", "format_scope", "length_scope", "comparison_period")
    required_numbers = ("winning_median", "comparison_median", "relative_difference")
    return (
        isinstance(count, int) and not isinstance(count, bool) and count >= 5
        and isinstance(comparison_count, int) and not isinstance(comparison_count, bool) and comparison_count >= 5
        and value.get("channel_id") == channel_id
        and all(isinstance(value.get(name), str) and value[name].strip() for name in required_text)
        and all(
            isinstance(value.get(name), (int, float))
            and not isinstance(value.get(name), bool)
            and math.isfinite(value[name])
            for name in required_numbers
        )
        and value["winning_median"] >= 0
        and value["comparison_median"] > 0
        and value["relative_difference"] > 0
    )
