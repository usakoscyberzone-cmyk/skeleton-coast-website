"""Read-only OAuth and analytics routes."""

from datetime import date, timedelta
import json
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from pathlib import Path
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ..config import get_settings, require_expected_youtube_channel_id
from ..db import begin_immediate_transaction, get_session
from ..models import VideoMetricSnapshot
from ..services.analytics_ingest import normalize_metrics, persist_metric_snapshot
from ..services.youtube_client import YouTubeApiError, YouTubeAuthorizationRequired, YouTubeClient, YouTubeConfigurationError, YouTubeOAuthCallbackError, YouTubeOAuthStateError, YouTubeQuotaError, YouTubeTokenChanged, YouTubeTransientError


router = APIRouter(prefix="/youtube", tags=["youtube"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


YOUTUBE_ROUTE_ERRORS = (
    YouTubeOAuthStateError,
    YouTubeOAuthCallbackError,
    YouTubeTokenChanged,
    YouTubeConfigurationError,
    YouTubeAuthorizationRequired,
    YouTubeQuotaError,
    YouTubeTransientError,
    YouTubeApiError,
    ValueError,
    PermissionError,
)


def normalized_retention_points(payload: str | None) -> list[dict[str, float]] | None:
    """Read legacy retention safely; only persisted normalized point arrays are usable."""
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    if not all(
        isinstance(point, dict)
        and isinstance(point.get("elapsed_ratio"), (int, float)) and not isinstance(point.get("elapsed_ratio"), bool) and math.isfinite(point["elapsed_ratio"])
        and isinstance(point.get("audience_retention"), (int, float)) and not isinstance(point.get("audience_retention"), bool) and math.isfinite(point["audience_retention"])
        for point in parsed
    ):
        return None
    if not all(
        0 <= float(point["elapsed_ratio"]) <= 1
        and float(point["audience_retention"]) >= 0
        for point in parsed
    ):
        return None
    return parsed


def _safe_nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return value if math.isfinite(number) and number >= 0 else None


def _safe_ratio(value):
    number = _safe_nonnegative(value)
    return number if number is not None and number <= 1 else None


def _safe_count(value):
    number = _safe_nonnegative(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _youtube_http_error(error: Exception) -> HTTPException:
    if isinstance(error, (YouTubeOAuthStateError, YouTubeOAuthCallbackError)):
        return HTTPException(status_code=400, detail="OAuth callback could not be validated.")
    if isinstance(error, YouTubeTokenChanged):
        return HTTPException(status_code=409, detail="YouTube authorization changed during the operation.")
    if isinstance(error, (YouTubeConfigurationError, ValueError, PermissionError)):
        return HTTPException(status_code=503, detail="YouTube credential storage is not securely configured.")
    if isinstance(error, YouTubeAuthorizationRequired):
        return HTTPException(status_code=401, detail="YouTube authorization is required.")
    if isinstance(error, YouTubeQuotaError):
        return HTTPException(status_code=503, detail="YouTube quota is temporarily unavailable.")
    if isinstance(error, YouTubeTransientError):
        return HTTPException(status_code=502, detail="YouTube upstream request failed.")
    if isinstance(error, YouTubeApiError):
        return HTTPException(status_code=502, detail="YouTube upstream request failed.")
    raise error


def get_youtube_client() -> YouTubeClient:
    settings = get_settings()
    if not settings.youtube_token_path:
        raise YouTubeConfigurationError("YOUTUBE_TOKEN_PATH is required")
    return YouTubeClient(
        token_path=Path(settings.youtube_token_path),
        client_secret_path=(Path(settings.youtube_client_secret_path) if settings.youtube_client_secret_path else None),
        redirect_uri=settings.youtube_redirect_uri,
    )


@router.get("/status")
def youtube_status() -> dict[str, str]:
    settings = get_settings()
    if not settings.expected_youtube_channel_id:
        return {
            "status": "configuration_required",
            "detail": "EXPECTED_YOUTUBE_CHANNEL_ID must be configured before analytics sync.",
        }
    if not settings.youtube_client_secret_path or not Path(settings.youtube_client_secret_path).is_file():
        return {"status": "configuration_required", "detail": "YOUTUBE_CLIENT_SECRET_PATH is required."}
    try:
        client = get_youtube_client()
        if not client.token_path.is_file():
            raise YouTubeAuthorizationRequired("YouTube authorization is required")
        channel = client.get_authenticated_channel()
    except YOUTUBE_ROUTE_ERRORS as error:
        raise _youtube_http_error(error) from error
    if channel.channel_id != settings.expected_youtube_channel_id:
        return {"status": "channel_mismatch", "detail": "Authorized channel does not match EXPECTED_YOUTUBE_CHANNEL_ID."}
    return {"status": "authorized", "channel_id": channel.channel_id, "channel_title": channel.title}


@router.get("/oauth/start")
def start_oauth() -> dict[str, str]:
    settings = get_settings()
    if not settings.youtube_client_secret_path or not Path(settings.youtube_client_secret_path).is_file():
        raise HTTPException(status_code=503, detail="YOUTUBE_CLIENT_SECRET_PATH is required before OAuth can start.")
    try:
        start = get_youtube_client().start_oauth()
    except YOUTUBE_ROUTE_ERRORS as error:
        raise _youtube_http_error(error) from error
    return {"authorization_url": start.authorization_url, "state": start.state}


@router.get("/oauth/callback")
def complete_oauth(code: str | None = None, state: str | None = None, error: str | None = None) -> dict[str, str]:
    try:
        if error:
            get_youtube_client().reject_oauth(state)
            raise YouTubeOAuthCallbackError("OAuth authorization was denied")
        if not code or not state:
            raise YouTubeOAuthStateError()
        get_youtube_client().complete_oauth(code=code, state=state)
    except YOUTUBE_ROUTE_ERRORS as error:
        raise _youtube_http_error(error) from error
    return {"status": "authorized"}


@router.post("/sync")
def sync_youtube(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict[str, str | int]:
    settings = get_settings()
    if not settings.expected_youtube_channel_id:
        raise HTTPException(
            status_code=503,
            detail="EXPECTED_YOUTUBE_CHANNEL_ID must be configured before analytics sync.",
        )
    try:
        client = get_youtube_client()
        guard = client.token_guard() if hasattr(client, "token_guard") else __import__("contextlib").nullcontext()
        with guard:
            channel = client.get_authenticated_channel()
            if channel.channel_id != settings.expected_youtube_channel_id:
                raise HTTPException(status_code=409, detail="V1 supports one channel only; the authorized channel does not match EXPECTED_YOUTUBE_CHANNEL_ID.")
            end_date = end_date or date.today()
            start_date = start_date or end_date - timedelta(days=28)
            pending = []
            for video in client.list_uploaded_videos(channel.uploads_playlist_id):
                seven_day_views = None
                if video.published_at is not None and hasattr(client, "fetch_video_views"):
                    first_day = video.published_at.date()
                    seventh_day = first_day + timedelta(days=6)
                    if end_date >= seventh_day:
                        seven_day_views = client.fetch_video_views(
                            video.video_id, first_day.isoformat(), seventh_day.isoformat()
                        )
                pending.append(normalize_metrics({**client.fetch_video_metrics(video.video_id, start_date.isoformat(), end_date.isoformat()).__dict__, "channel_id": channel.channel_id, "views_7d": seven_day_views, "title": video.title, "published_at": video.published_at, "duration_seconds": video.duration_seconds, "video_type": video.video_type}))
            begin_immediate_transaction(session)
            for metric in pending:
                persist_metric_snapshot(session, metric, start_date=start_date, end_date=end_date)
            def validate_token_before_commit(_session):
                client.ensure_token_unchanged()

            event.listen(session, "before_commit", validate_token_before_commit, once=True)
            session.commit()
            return {"status": "synced", "channel_id": channel.channel_id, "channel_title": channel.title, "video_count": len(pending)}
    except HTTPException:
        session.rollback()
        raise
    except YOUTUBE_ROUTE_ERRORS as error:
        session.rollback()
        raise _youtube_http_error(error) from error


@analytics_router.get("/summary")
def analytics_summary(
    session: Session = Depends(get_session),
    channel_id: str = Depends(require_expected_youtube_channel_id),
) -> dict:
    rows = list(session.scalars(
        select(VideoMetricSnapshot).where(VideoMetricSnapshot.channel_id == channel_id)
    ))
    # Preserve only the most recent row per video without claiming missing metrics are zero.
    latest = []
    seen = set()
    for row in sorted(rows, key=lambda r: (r.analytics_end_date or date.min, r.captured_at, r.id), reverse=True):
        if row.youtube_video_id not in seen:
            seen.add(row.youtube_video_id)
            latest.append(row)
    def aggregate(name):
        validator = _safe_count if name in {
            "views", "impressions", "subscribers_gained", "returning_viewers",
            "views_1h", "views_24h", "views_7d",
        } else _safe_nonnegative
        known = [value for row in latest if (value := validator(getattr(row, name))) is not None]
        return {"value": sum(known) if known else None, "coverage": len(known)}
    def weighted(metric_name, denominator_name):
        metric_validator = _safe_ratio if metric_name in {"ctr", "average_percentage_viewed"} else _safe_nonnegative
        pairs = [
            (metric, denominator) for row in latest
            if (metric := metric_validator(getattr(row, metric_name))) is not None
            and (denominator := _safe_count(getattr(row, denominator_name))) is not None
            and denominator > 0
        ]
        denominator = sum(pair[1] for pair in pairs)
        return {"value": sum(value * weight for value, weight in pairs) / denominator if denominator else None, "coverage": len(pairs)}
    def conversion_rate():
        pairs = [
            (subscribers, views) for row in latest
            if (subscribers := _safe_count(row.subscribers_gained)) is not None
            and (views := _safe_count(row.views)) is not None and views > 0
            and subscribers <= views
        ]
        denominator = sum(pair[1] for pair in pairs)
        return {"value": sum(pair[0] for pair in pairs) / denominator if denominator else None, "coverage": len(pairs)}
    def leader(kind: str):
        candidates = [
            (row, views) for row in latest
            if (views := _safe_count(row.views)) is not None
            and (row.video_type or row.format or "").lower() == kind
        ]
        if not candidates:
            return None
        row, views = min(candidates, key=lambda candidate: (-candidate[1], candidate[0].youtube_video_id))
        return {"id": row.youtube_video_id, "title": row.title or row.youtube_video_id, "views": views}
    # Shares are already normalized per video. Weight each source only by videos
    # that supplied both that source and views; missing source data is not zero.
    traffic_sources = {}
    traffic_source_coverage = {}
    for label, field in (("Browse", "browse_share"), ("Suggested", "suggested_share"), ("Search", "search_share"), ("External", "external_share"), ("Shorts Feed", "shorts_feed_share")):
        contributing = [
            (row, views, share) for row in latest
            if (views := _safe_count(row.views)) is not None
            and (share := _safe_ratio(getattr(row, field))) is not None
        ]
        if contributing:
            traffic_source_coverage[label] = len(contributing)
            denominator = sum(views for _row, views, _share in contributing)
            if denominator:
                traffic_sources[label] = sum(views * share for _row, views, share in contributing) / denominator
    topics = {}
    for topic in ("Fishing", "Namibia travel", "Angola", "History", "4x4", "Current events"):
        matching = [views for row in latest if row.topic == topic and (views := _safe_count(row.views)) is not None]
        topics[topic] = {"value": sum(matching) if matching else None, "coverage": len(matching)}
    videos = [
        {"id": row.youtube_video_id, "title": row.title or row.youtube_video_id, "views": _safe_count(row.views)}
        for row in sorted(latest, key=lambda item: ((_safe_count(item.views) is None), -(_safe_count(item.views) or 0), item.youtube_video_id))
        if _safe_count(row.views) is not None
    ]
    retention_videos = [
        {"id": row.youtube_video_id, "title": row.title or row.youtube_video_id}
        for row in sorted(latest, key=lambda item: item.youtube_video_id)
        if normalized_retention_points(row.retention_json) is not None
    ]
    return {
        "video_count": len(latest),
        "views": aggregate("views"), "watch_minutes": aggregate("watch_minutes"), "subscribers_gained": aggregate("subscribers_gained"),
        "impressions": aggregate("impressions"), "ctr": weighted("ctr", "impressions"),
        "avg_view_duration_seconds": weighted("avg_view_duration_seconds", "views"),
        "average_percentage_viewed": weighted("average_percentage_viewed", "views"),
        "subscriber_conversion_rate": conversion_rate(),
        "returning_viewers": aggregate("returning_viewers"),
        "views_1h": aggregate("views_1h"), "views_24h": aggregate("views_24h"), "views_7d": aggregate("views_7d"),
        "top_long_form": leader("long"),
        "top_short": leader("short"),
        "traffic_sources": traffic_sources, "traffic_source_coverage": traffic_source_coverage,
        "videos": videos, "retention_videos": retention_videos, "topics": topics,
    }


@analytics_router.get("/videos/{video_id}/retention")
def retention_data(
    video_id: str,
    session: Session = Depends(get_session),
    channel_id: str = Depends(require_expected_youtube_channel_id),
) -> dict:
    snapshot = session.scalar(
        select(VideoMetricSnapshot)
        .where(
            VideoMetricSnapshot.channel_id == channel_id,
            VideoMetricSnapshot.youtube_video_id == video_id,
        )
        .order_by(VideoMetricSnapshot.captured_at.desc())
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Video metrics not found")
    return {"video_id": video_id, "retention": normalized_retention_points(snapshot.retention_json)}
