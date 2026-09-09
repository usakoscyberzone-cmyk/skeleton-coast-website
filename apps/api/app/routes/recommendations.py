"""Read-only recommendation endpoints; these never call YouTube write APIs."""

from datetime import UTC, datetime
import json
import math

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import begin_immediate_transaction, get_session
from ..config import require_expected_youtube_channel_id
from ..models import Recommendation, VideoMetricSnapshot
from ..services.baselines import build_channel_baseline, length_bucket
from ..services.recommendation_engine import VideoDecisionContext, evaluate_video


router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/active")
def active_recommendations(
    session: Session = Depends(get_session),
    channel_id: str = Depends(require_expected_youtube_channel_id),
) -> list[dict]:
    rows = session.scalars(
        select(Recommendation).where(
            Recommendation.channel_id == channel_id,
            Recommendation.is_active.is_(True),
        ).order_by(Recommendation.id)
    )
    return [_serialize(row) for row in rows]


@router.post("/rebuild")
def rebuild_recommendations(
    session: Session = Depends(get_session),
    channel_id: str = Depends(require_expected_youtube_channel_id),
) -> dict[str, int]:
    snapshots = _latest_snapshots(session, channel_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    decisions = []
    for snapshot in snapshots:
        comparable = [row for row in snapshots if row.youtube_video_id != snapshot.youtube_video_id]
        baseline = build_channel_baseline(
            snapshot.topic or "", (snapshot.format or snapshot.video_type or "").lower(),
            length_bucket(snapshot.length_seconds or snapshot.duration_seconds), comparable,
        )
        previous = _previous_snapshot(session, snapshot, channel_id)
        decisions.append((snapshot.youtube_video_id, evaluate_video(VideoDecisionContext(
            age_hours=_safe_nonnegative(_age_hours(snapshot.published_at, now)), impressions=_safe_count(snapshot.impressions),
            ctr=_safe_ratio(snapshot.ctr), avg_percentage_viewed=_safe_ratio(snapshot.average_percentage_viewed),
            browse_trend=_change(snapshot.browse_share, previous.browse_share if previous else None),
            suggested_trend=_change(snapshot.suggested_share, previous.suggested_share if previous else None),
            realtime_trend=_view_trend(snapshot.views, previous.views if previous else None),
            external_share=_safe_ratio(snapshot.external_share), comparable_sample_size=baseline.sample_size,
            comparable_ctr=baseline.ctr, comparable_retention=baseline.retention,
        ))))
    begin_immediate_transaction(session)
    session.execute(
        update(Recommendation)
        .where(Recommendation.channel_id == channel_id)
        .values(is_active=False)
    )
    for video_id, decision in decisions:
        session.add(Recommendation(channel_id=channel_id, youtube_video_id=video_id, state=decision.state, action=decision.action,
                                   reason=decision.reason, confidence=decision.confidence,
                                   data_used_json=json.dumps(decision.data_used, allow_nan=False), is_active=True))
    session.commit()
    return {"rebuilt": len(decisions)}


def _latest_snapshots(session: Session, channel_id: str) -> list[VideoMetricSnapshot]:
    rows = list(session.scalars(
        select(VideoMetricSnapshot).where(VideoMetricSnapshot.channel_id == channel_id)
    ))
    latest: dict[str, VideoMetricSnapshot] = {}
    for row in rows:
        current = latest.get(row.youtube_video_id)
        if current is None or (row.captured_at, row.id) > (current.captured_at, current.id):
            latest[row.youtube_video_id] = row
    return [latest[key] for key in sorted(latest)]


def _previous_snapshot(session: Session, latest: VideoMetricSnapshot, channel_id: str) -> VideoMetricSnapshot | None:
    return session.scalar(select(VideoMetricSnapshot).where(
        VideoMetricSnapshot.channel_id == channel_id,
        VideoMetricSnapshot.youtube_video_id == latest.youtube_video_id,
        VideoMetricSnapshot.id != latest.id,
    ).order_by(VideoMetricSnapshot.captured_at.desc(), VideoMetricSnapshot.id.desc()))


def _age_hours(published_at, now: datetime) -> float | None:
    if published_at is None:
        return None
    return max(0.0, (now.replace(tzinfo=UTC) - published_at).total_seconds() / 3600)


def _change(current: float | None, previous: float | None) -> float | None:
    current = _safe_ratio(current)
    previous = _safe_ratio(previous)
    return current - previous if current is not None and previous is not None else None


def _view_trend(current: int | None, previous: int | None) -> float | None:
    current = _safe_count(current)
    previous = _safe_count(previous)
    if current is None or previous is None:
        return None
    if previous == 0:
        return 1.0 if current > 0 else 0.0
    return (current - previous) / previous


def _safe_nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return value if math.isfinite(number) and number >= 0 else None


def _safe_ratio(value):
    value = _safe_nonnegative(value)
    return value if value is not None and value <= 1 else None


def _safe_count(value):
    value = _safe_nonnegative(value)
    return int(value) if value is not None and float(value).is_integer() else None


def _serialize(row: Recommendation) -> dict:
    try:
        data_used = _sanitize_json_value(json.loads(row.data_used_json))
    except (TypeError, json.JSONDecodeError):
        data_used = {}
    return {"id": row.id, "youtube_video_id": row.youtube_video_id, "state": row.state,
            "action": row.action, "reason": row.reason, "confidence": row.confidence,
            "data_used": data_used}


def _sanitize_json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    return value
