from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_session, upgrade_video_metrics_schema
from app.main import create_app
from app.models import VideoMetricSnapshot
from app.routes import youtube as youtube_routes
from app.services.youtube_client import (
    YouTubeApiError,
    YouTubeAuthorizationRequired,
    YouTubeClient,
    YouTubeOAuthCallbackError,
    YouTubeOAuthStateError,
    YouTubeQuotaError,
    YouTubeTokenChanged,
    YouTubeTransientError,
)


def test_migration_preserves_real_index_names_when_legacy_period_name_collides(tmp_path):
    database = tmp_path / "legacy-named-index.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE video_metric_snapshots ("
            "id INTEGER PRIMARY KEY, youtube_video_id VARCHAR(32) NOT NULL, "
            "captured_at DATETIME NOT NULL, analytics_start_date DATE, "
            "analytics_end_date DATE, views INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_video_metric_period ON video_metric_snapshots "
            "(youtube_video_id, analytics_start_date, analytics_end_date)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_video_metric_legacy_capture ON video_metric_snapshots (captured_at)"
        )
        connection.exec_driver_sql(
            "INSERT INTO video_metric_snapshots VALUES "
            "(1, 'v1', '2026-09-01', NULL, NULL, 10)"
        )

    upgrade_video_metrics_schema(engine)
    upgrade_video_metrics_schema(engine)

    with Session(engine) as session:
        from app.services.analytics_ingest import normalize_metrics, persist_metric_snapshot

        metric = normalize_metrics({"video_id": "v1", "views": 30})
        persist_metric_snapshot(session, metric, start_date=None, end_date=None)
        persist_metric_snapshot(session, metric, start_date=None, end_date=None)
        session.commit()
        rows = list(session.scalars(select(VideoMetricSnapshot)))

    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='video_metric_snapshots'"
            )
        }
    assert indexes >= {"uq_video_metric_period", "ix_video_metric_legacy_capture"}
    assert len(rows) == 1
    assert rows[0].views == 30


def test_os_lock_still_excludes_second_client_while_visible_artifact_is_removed_and_recreated(
    tmp_path, monkeypatch
):
    token = tmp_path / "private-lock" / "token.json"
    monkeypatch.setattr(YouTubeClient, "_secure_acl", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(
        YouTubeClient, "_verify_owner_only_acl", staticmethod(lambda *_args, **_kwargs: None)
    )
    first = YouTubeClient(token_path=token)
    second = YouTubeClient(token_path=token)
    lock_path = token.with_name(token.name + ".lock")

    with first.token_guard():
        lock_path.unlink()
        lock_path.write_text("replacement", encoding="utf-8")
        lock_path.unlink()
        try:
            with pytest.raises(YouTubeTokenChanged, match="already in use"):
                with second.token_guard():
                    pass
        finally:
            lock_path.write_text("replacement", encoding="utf-8")


def test_token_replacement_inside_session_commit_returns_409_without_committing_rows(
    tmp_path, monkeypatch
):
    database = tmp_path / "commit-window.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    token = tmp_path / "private-token" / "token.json"
    monkeypatch.setattr(YouTubeClient, "_secure_acl", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(
        YouTubeClient, "_verify_owner_only_acl", staticmethod(lambda *_args, **_kwargs: None)
    )
    YouTubeClient._write(token, '{"token":"original"}')
    client = YouTubeClient(token_path=token)
    client._token_digest = hashlib.sha256(token.read_bytes()).digest()
    monkeypatch.setattr(
        client,
        "get_authenticated_channel",
        lambda: SimpleNamespace(channel_id="UC-ok", title="ok", uploads_playlist_id="UU-ok"),
    )
    monkeypatch.setattr(
        client,
        "list_uploaded_videos",
        lambda _playlist: [
            SimpleNamespace(
                video_id="v1",
                title="Video",
                published_at=datetime.fromisoformat("2026-09-01T10:00:00+00:00"),
                duration_seconds=60,
                video_type="unknown",
            )
        ],
    )
    monkeypatch.setattr(
        client,
        "fetch_video_metrics",
        lambda *_args: SimpleNamespace(
            video_id="v1",
            views=5,
            watch_minutes=None,
            avg_view_duration_seconds=None,
            average_percentage_viewed=None,
            subscribers_gained=None,
            impressions=None,
            ctr=None,
            returning_viewers=None,
            traffic_raw={},
        ),
    )
    original_commit = session.commit

    def replace_token_then_commit():
        token.write_text('{"token":"replacement"}', encoding="utf-8")
        original_commit()

    monkeypatch.setattr(session, "commit", replace_token_then_commit)
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok")
    get_settings.cache_clear()
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: client)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    response = TestClient(app).post(
        "/youtube/sync?start_date=2026-09-01&end_date=2026-09-02"
    )

    session.close()
    with Session(engine) as verification_session:
        rows = list(verification_session.scalars(select(VideoMetricSnapshot)))
    get_settings.cache_clear()
    assert response.status_code == 409
    assert rows == []


def _configured_route_app(monkeypatch, tmp_path, client):
    secret = tmp_path / "client.json"
    token = tmp_path / "token.json"
    secret.write_text("{}", encoding="utf-8")
    token.write_text("{}", encoding="utf-8")
    client.token_path = token
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_PATH", str(secret))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", str(token))
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok")
    get_settings.cache_clear()
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: client)
    return create_app()


@pytest.mark.parametrize(
    ("route", "method_name"),
    [
        ("/youtube/status", "get"),
        ("/youtube/oauth/start", "get"),
        ("/youtube/oauth/callback?code=code&state=state", "get"),
        ("/youtube/sync", "post"),
    ],
)
def test_missing_youtube_token_path_is_503_on_every_youtube_route(
    route, method_name, monkeypatch, tmp_path
):
    secret = tmp_path / "client.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_PATH", str(secret))
    monkeypatch.delenv("YOUTUBE_TOKEN_PATH", raising=False)
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok")
    get_settings.cache_clear()

    response = getattr(TestClient(create_app(), raise_server_exceptions=False), method_name)(route)

    get_settings.cache_clear()
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("route", "method_name"),
    [
        ("/youtube/status", "get"),
        ("/youtube/oauth/start", "get"),
        ("/youtube/oauth/callback?code=code&state=state", "get"),
        ("/youtube/sync", "post"),
    ],
)
def test_relative_youtube_token_path_is_503_on_every_youtube_route(
    route, method_name, monkeypatch, tmp_path
):
    secret = tmp_path / "client.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET_PATH", str(secret))
    monkeypatch.setenv("YOUTUBE_TOKEN_PATH", "private/token.json")
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok")
    get_settings.cache_clear()

    response = getattr(TestClient(create_app(), raise_server_exceptions=False), method_name)(route)

    get_settings.cache_clear()
    assert response.status_code == 503


class _BoundaryFailureClient:
    def __init__(self, error):
        self.error = error

    @contextmanager
    def token_guard(self):
        yield

    def get_authenticated_channel(self):
        raise self.error

    def start_oauth(self):
        raise self.error

    def complete_oauth(self, **_kwargs):
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (YouTubeAuthorizationRequired("revoked"), 401),
        (YouTubeTokenChanged("conflict"), 409),
        (YouTubeQuotaError("quota"), 503),
        (YouTubeTransientError("transient"), 502),
        (YouTubeApiError("upstream"), 502),
    ],
)
@pytest.mark.parametrize(
    ("route", "method_name"),
    [
        ("/youtube/status", "get"),
        ("/youtube/oauth/start", "get"),
        ("/youtube/oauth/callback?code=code&state=state", "get"),
        ("/youtube/sync", "post"),
    ],
)
def test_youtube_error_taxonomy_is_consistent_at_each_route_boundary(
    error, expected_status, route, method_name, monkeypatch, tmp_path
):
    app = _configured_route_app(monkeypatch, tmp_path, _BoundaryFailureClient(error))

    response = getattr(TestClient(app, raise_server_exceptions=False), method_name)(route)

    get_settings.cache_clear()
    assert response.status_code == expected_status


@pytest.mark.parametrize("error", [YouTubeOAuthStateError("bad state"), YouTubeOAuthCallbackError("denied")])
def test_callback_validation_and_denial_are_400(error, monkeypatch, tmp_path):
    app = _configured_route_app(monkeypatch, tmp_path, _BoundaryFailureClient(error))

    response = TestClient(app, raise_server_exceptions=False).get(
        "/youtube/oauth/callback?code=code&state=state"
    )

    get_settings.cache_clear()
    assert response.status_code == 400


def test_callback_token_write_conflict_is_409(monkeypatch, tmp_path):
    app = _configured_route_app(
        monkeypatch, tmp_path, _BoundaryFailureClient(YouTubeTokenChanged("changed"))
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/youtube/oauth/callback?code=code&state=state"
    )

    get_settings.cache_clear()
    assert response.status_code == 409


def test_relative_token_path_is_rejected_before_resolution_from_temporary_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        YouTubeClient(token_path=Path("private/token.json"))
