from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, upgrade_video_metrics_schema
from app.main import create_app
from app.models import VideoMetricSnapshot
from app.routes import youtube as youtube_routes
from app.services.analytics_ingest import normalize_metrics, persist_metric_snapshot
from app.services.youtube_client import (
    RawVideoMetrics,
    YouTubeAuthorizationRequired,
    YouTubeClient,
    YouTubeQuotaError,
    YouTubeTokenChanged,
    YouTubeTransientError,
)


def test_legacy_migration_keeps_highest_id_for_null_period_and_recreates_indexes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE video_metric_snapshots (id INTEGER PRIMARY KEY, youtube_video_id VARCHAR(32) NOT NULL, captured_at DATETIME NOT NULL, views INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE INDEX ix_video_metric_snapshots_youtube_video_id ON video_metric_snapshots (youtube_video_id)")
        connection.exec_driver_sql("CREATE INDEX ix_video_metric_snapshots_captured_at ON video_metric_snapshots (captured_at)")
        connection.exec_driver_sql("INSERT INTO video_metric_snapshots VALUES (1, 'v1', '2026-09-01', 10), (2, 'v1', '2026-09-02', 20)")
    upgrade_video_metrics_schema(engine)
    with Session(engine) as session:
        rows = list(session.scalars(select(VideoMetricSnapshot)))
        assert [(row.id, row.views) for row in rows] == [(2, 20)]
        metric = normalize_metrics({"video_id": "v1", "views": 30})
        persist_metric_snapshot(session, metric, start_date=None, end_date=None)
        persist_metric_snapshot(session, metric, start_date=None, end_date=None)
        session.commit()
        assert session.scalar(select(VideoMetricSnapshot).where(VideoMetricSnapshot.youtube_video_id == "v1")).views == 30
        assert len(list(session.scalars(select(VideoMetricSnapshot)))) == 1
    names = {item["name"] for item in inspect(engine).get_indexes("video_metric_snapshots")}
    assert "ix_video_metric_snapshots_youtube_video_id" in names
    assert "ix_video_metric_snapshots_captured_at" in names


def test_live_traffic_counts_use_raw_total_but_frozen_fixture_stays_normalized():
    live = normalize_metrics(RawVideoMetrics(video_id="v", traffic_raw={"BROWSE": 240, "RELATED_VIDEO": 60, "EXT_URL": 100}))
    assert live.browse_share == 0.6
    assert live.suggested_share == 0.15
    frozen = normalize_metrics({"video_id": "v", "ctr": .071, "traffic": {"BROWSE": .576, "SUGGESTED": .04}})
    assert frozen.ctr == .071
    assert frozen.browse_share == .576


def test_public_normalizer_annotation_resolves_raw_metrics():
    assert get_type_hints(normalize_metrics)["raw"] == RawVideoMetrics | dict[str, object]


def test_published_at_round_trips_as_utc(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'utc.db'}")
    Base.metadata.create_all(engine)
    metric = normalize_metrics({"video_id": "v", "published_at": datetime(2026, 9, 1, 10, tzinfo=UTC)})
    with Session(engine) as session:
        persist_metric_snapshot(session, metric, start_date=date(2026, 9, 1), end_date=date(2026, 9, 2)); session.commit()
    with Session(engine) as session:
        value = session.scalar(select(VideoMetricSnapshot)).published_at
        assert value == datetime(2026, 9, 1, 10, tzinfo=UTC)
        assert value.tzinfo is UTC


def test_state_consume_uses_unique_name_and_cleans_up_after_malformed_json(tmp_path, monkeypatch):
    client = YouTubeClient(token_path=tmp_path / "token.json")
    client.oauth_state_path.write_text("not-json", encoding="utf-8")
    moved = []
    original_replace = Path.replace
    def track_replace(self, target):
        moved.append(Path(target)); return original_replace(self, target)
    monkeypatch.setattr(Path, "replace", track_replace)
    with pytest.raises(Exception):
        client._consume_state()
    assert moved and ".consumed." in moved[0].name
    assert not moved[0].exists()


def test_secure_write_verifies_parent_temp_and_destination_in_order(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(YouTubeClient, "_secure_acl", staticmethod(lambda path, directory=False: events.append((Path(path).name, directory))))
    monkeypatch.setattr(YouTubeClient, "_verify_owner_only_acl", staticmethod(lambda path, directory=False: events.append((Path(path).name, directory))))
    target = tmp_path / "private" / "token.json"
    YouTubeClient._write(target, "secret")
    assert events[0] == ("private", True)
    assert events[1][0].endswith(".tmp")
    assert events[-1] == ("token.json", False)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_windows_secure_write_applies_owner_only_acl(tmp_path):
    target = tmp_path / "private" / "token.json"
    YouTubeClient._write(target, "secret")
    YouTubeClient._verify_owner_only_acl(target.parent, directory=True)
    YouTubeClient._verify_owner_only_acl(target, directory=False)


class _RefreshableCredentials:
    expired = True
    refresh_token = "refresh"
    def __init__(self): self.token = "old"; self.refreshes = 0
    def refresh(self, request): self.refreshes += 1; self.token = "new"
    def to_json(self): return json.dumps({"token": self.token})


def test_expired_credentials_refresh_and_are_durably_persisted(tmp_path, monkeypatch):
    token = tmp_path / "private-refresh" / "token.json"; YouTubeClient._write(token, '{"token":"old"}')
    creds = _RefreshableCredentials()
    client = YouTubeClient(token_path=token, credentials_loader=lambda *_: creds)
    monkeypatch.setattr(client, "_refresh_request", lambda: object())
    client._load()
    assert creds.refreshes == 1
    assert json.loads(token.read_text())["token"] == "new"
    client.ensure_token_unchanged()


def test_refresh_fails_closed_if_token_replaced_or_disappears(tmp_path, monkeypatch):
    for replacement in ('{"token":"other"}', None):
        token = tmp_path / ("private-cas-" + str(replacement is None)) / "token.json"; YouTubeClient._write(token, '{"token":"old"}')
        creds = _RefreshableCredentials()
        client = YouTubeClient(token_path=token, credentials_loader=lambda *_: creds)
        monkeypatch.setattr(client, "_refresh_request", lambda: object())
        def mutate(_):
            token.write_text(replacement) if replacement is not None else token.unlink()
        monkeypatch.setattr(creds, "refresh", mutate)
        with pytest.raises(YouTubeTokenChanged): client._load()


def test_sync_maps_commit_window_token_replacement_to_409_and_rolls_back(monkeypatch, tmp_path):
    class Client:
        @contextmanager
        def token_guard(self): yield
        def get_authenticated_channel(self): return SimpleNamespace(channel_id="UC-ok", title="ok", uploads_playlist_id="UU")
        def list_uploaded_videos(self, _): return []
        def ensure_token_unchanged(self): raise YouTubeTokenChanged("changed")
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok"); get_settings.cache_clear()
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: Client())
    response = TestClient(create_app()).post("/youtube/sync")
    assert response.status_code == 409
    get_settings.cache_clear()


@pytest.mark.parametrize(("error", "status"), [(YouTubeAuthorizationRequired("x"),401),(YouTubeTokenChanged("x"),409),(YouTubeQuotaError("x"),503),(YouTubeTransientError("x"),502)])
def test_sync_classifies_failures_from_any_boundary(monkeypatch, error, status):
    class Client:
        @contextmanager
        def token_guard(self): yield
        def get_authenticated_channel(self): return SimpleNamespace(channel_id="UC-ok", title="ok", uploads_playlist_id="UU")
        def list_uploaded_videos(self, _): raise error
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok"); get_settings.cache_clear()
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: Client())
    assert TestClient(create_app()).post("/youtube/sync").status_code == status
    get_settings.cache_clear()


def test_callback_denial_is_a_validated_http_400(monkeypatch):
    class Client:
        def reject_oauth(self, state): assert state == "valid"
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: Client())
    response = TestClient(create_app()).get("/youtube/oauth/callback?error=access_denied&state=valid")
    assert response.status_code == 400


def test_sync_maps_invalid_credential_configuration_to_503(monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-ok"); get_settings.cache_clear()
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: (_ for _ in ()).throw(ValueError("unsafe path")))
    response = TestClient(create_app(), raise_server_exceptions=False).post("/youtube/sync")
    assert response.status_code == 503
    get_settings.cache_clear()


def test_completed_oauth_token_write_is_serialized_by_token_guard(tmp_path, monkeypatch):
    class Credentials:
        def to_json(self): return '{"token":"secret"}'
    class Flow:
        credentials = Credentials()
        def fetch_token(self, *, code): assert code == "code"
    client = YouTubeClient(token_path=tmp_path / "private-lock" / "token.json", client_secret_path=tmp_path / "client.json", flow_factory=lambda **_: Flow())
    monkeypatch.setattr(client, "_consume_state", lambda: "valid")
    events = []
    @contextmanager
    def guard():
        events.append("enter"); yield; events.append("exit")
    monkeypatch.setattr(client, "token_guard", guard)
    original_write = client._write
    monkeypatch.setattr(client, "_write", lambda *args, **kwargs: (events.append("write"), original_write(*args, **kwargs))[1])
    client.complete_oauth(code="code", state="valid")
    assert events == ["enter", "write", "exit"]
