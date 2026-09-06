"""Read-only OAuth and analytics routes."""

from datetime import date, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import begin_immediate_transaction, get_session
from ..models import VideoMetricSnapshot
from ..services.analytics_ingest import normalize_metrics, persist_metric_snapshot
from ..services.youtube_client import YouTubeApiError, YouTubeAuthorizationRequired, YouTubeClient, YouTubeOAuthStateError, YouTubeQuotaError, YouTubeTokenChanged, YouTubeTransientError


router = APIRouter(prefix="/youtube", tags=["youtube"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_youtube_client() -> YouTubeClient:
    settings = get_settings()
    if not settings.youtube_token_path:
        raise YouTubeAuthorizationRequired("YOUTUBE_TOKEN_PATH is required")
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
    if not settings.youtube_token_path or not Path(settings.youtube_token_path).is_file():
        return {"status": "authorization_required", "detail": "YouTube authorization is required."}
    try:
        channel = get_youtube_client().get_authenticated_channel()
    except YouTubeAuthorizationRequired:
        return {"status": "authorization_required", "detail": "YouTube authorization is required."}
    except YouTubeApiError:
        return {"status": "authorization_required", "detail": "YouTube authorization must be renewed."}
    if channel.channel_id != settings.expected_youtube_channel_id:
        return {"status": "channel_mismatch", "detail": "Authorized channel does not match EXPECTED_YOUTUBE_CHANNEL_ID."}
    return {"status": "authorized", "channel_id": channel.channel_id, "channel_title": channel.title}


@router.get("/oauth/start")
def start_oauth() -> dict[str, str]:
    settings = get_settings()
    if not settings.youtube_client_secret_path or not Path(settings.youtube_client_secret_path).is_file():
        raise HTTPException(status_code=503, detail="YOUTUBE_CLIENT_SECRET_PATH is required before OAuth can start.")
    start = get_youtube_client().start_oauth()
    return {"authorization_url": start.authorization_url, "state": start.state}


@router.get("/oauth/callback")
def complete_oauth(code: str | None = None, state: str | None = None, error: str | None = None) -> dict[str, str]:
    try:
        if error:
            get_youtube_client().reject_oauth(state)
            return {"status": "authorization_denied"}
        if not code or not state:
            raise YouTubeOAuthStateError()
        get_youtube_client().complete_oauth(code=code, state=state)
    except YouTubeOAuthStateError as error:
        raise HTTPException(status_code=400, detail="OAuth callback could not be validated.") from error
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
    client = get_youtube_client()
    try:
        channel = client.get_authenticated_channel()
    except YouTubeAuthorizationRequired as error:
        raise HTTPException(status_code=401, detail="YouTube authorization is required.") from error
    except YouTubeTokenChanged as error:
        raise HTTPException(status_code=409, detail="YouTube authorization changed during sync.") from error
    except YouTubeQuotaError as error:
        raise HTTPException(status_code=503, detail="YouTube quota is temporarily unavailable.") from error
    except (YouTubeTransientError, YouTubeApiError) as error:
        raise HTTPException(status_code=502, detail="YouTube upstream request failed.") from error
    if channel.channel_id != settings.expected_youtube_channel_id:
        raise HTTPException(
            status_code=409,
            detail="V1 supports one channel only; the authorized channel does not match EXPECTED_YOUTUBE_CHANNEL_ID.",
        )
    end_date = end_date or date.today()
    start_date = start_date or end_date - timedelta(days=28)
    pending = []
    count = 0
    for video in client.list_uploaded_videos(channel.uploads_playlist_id):
        metric = normalize_metrics(
            {
                **client.fetch_video_metrics(video.video_id, start_date.isoformat(), end_date.isoformat()).__dict__,
                "title": video.title,
                "duration_seconds": video.duration_seconds,
                "video_type": video.video_type,
            }
        )
        pending.append(metric)
        count += 1
    begin_immediate_transaction(session)
    for metric in pending:
        persist_metric_snapshot(session, metric, start_date=start_date, end_date=end_date)
    client.ensure_token_unchanged()
    session.commit()
    return {"status": "synced", "channel_id": channel.channel_id, "channel_title": channel.title, "video_count": count}


@analytics_router.get("/summary")
def analytics_summary(session: Session = Depends(get_session)) -> dict:
    rows = list(session.scalars(select(VideoMetricSnapshot)))
    # Preserve only the most recent row per video without claiming missing metrics are zero.
    latest = []
    seen = set()
    for row in sorted(rows, key=lambda r: (r.analytics_end_date or date.min, r.captured_at, r.id), reverse=True):
        if row.youtube_video_id not in seen:
            seen.add(row.youtube_video_id)
            latest.append(row)
    def aggregate(name):
        known=[getattr(row,name) for row in latest if getattr(row,name) is not None]
        return {"value": sum(known) if known else None, "coverage": len(known)}
    return {
        "video_count": len(latest),
        "views": aggregate("views"), "watch_minutes": aggregate("watch_minutes"), "subscribers_gained": aggregate("subscribers_gained"),
    }


@analytics_router.get("/videos/{video_id}/retention")
def retention_data(video_id: str, session: Session = Depends(get_session)) -> dict:
    snapshot = session.scalar(
        select(VideoMetricSnapshot)
        .where(VideoMetricSnapshot.youtube_video_id == video_id)
        .order_by(VideoMetricSnapshot.captured_at.desc())
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Video metrics not found")
    return {"video_id": video_id, "retention": json.loads(snapshot.retention_json) if snapshot.retention_json else None}
