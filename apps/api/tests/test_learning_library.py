from dataclasses import replace
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_session, upgrade_video_metrics_schema
from app.main import create_app
from app.models import LearningPattern, VideoMetricSnapshot
from app.routes import youtube as youtube_routes
from app.services.youtube_client import ChannelIdentity, RawVideoMetrics, UploadedVideo
from app.services.learning_library import (
    ChannelDataset,
    ChannelVideo,
    extract_learning_patterns,
)


def _videos(**changes):
    values = []
    for number in range(10):
        defaults = {
            "video_id": f"video-{number}",
            "topic": "Fishing",
            "format": "long",
            "length_seconds": 600,
            "comparison_period": "2026-08-01/2026-08-28",
        }
        defaults.update({key: value(number) if callable(value) else value for key, value in changes.items()})
        values.append(ChannelVideo(**defaults))
    return values


def _pattern(pattern_type, videos):
    return next(
        pattern
        for pattern in extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos))
        if pattern.pattern_type == pattern_type
    )


def test_pattern_requires_minimum_evidence():
    dataset = ChannelDataset(
        channel_id="UC-skeleton",
        videos=_videos(topic=lambda number: "Fishing" if number < 3 else None, views=100)[:3],
    )

    assert extract_learning_patterns(dataset) == []


@pytest.mark.parametrize(
    ("pattern_type", "changes", "winning_scope"),
    [
        ("thumbnail_wording", {"thumbnail_wording": lambda n: "mystery" if n < 5 else "plain", "ctr": lambda n: .08 if n < 5 else .04}, "mystery"),
        ("hook_type", {"hook_type": lambda n: "reveal" if n < 5 else "question", "average_percentage_viewed": lambda n: .60 if n < 5 else .40}, "reveal"),
        ("topic_performance", {"topic": lambda n: "Fishing" if n < 5 else "History", "views": lambda n: 200 if n < 5 else 100}, "Fishing"),
        ("short_duration", {"format": "short", "length_seconds": lambda n: 20 if n < 5 else 50, "average_percentage_viewed": lambda n: .80 if n < 5 else .40}, "under 30s"),
        ("subscriber_conversion", {"format": lambda n: "long" if n < 5 else "short", "subscriber_conversion_rate": lambda n: .02 if n < 5 else .01}, "long"),
        ("browse_suggested_response", {"browse_share": lambda n: .55 if n < 5 else .10, "suggested_share": .10, "views_7d": lambda n: 200 if n < 5 else 100}, "browse/suggested-led"),
        ("geography", {"geography": lambda n: "Namibia" if n < 5 else "South Africa", "views": lambda n: 200 if n < 5 else 100}, "Namibia"),
        ("follow_up_performance", {"is_follow_up": lambda n: n < 5, "views_7d": lambda n: 200 if n < 5 else 100}, "follow-up"),
    ],
)
def test_each_learning_type_reports_only_literal_channel_evidence(pattern_type, changes, winning_scope):
    pattern = _pattern(pattern_type, _videos(**changes))

    assert pattern.pattern_type == pattern_type
    assert pattern.evidence["winning_group"] == winning_scope
    assert pattern.evidence["comparison_group"]
    assert pattern.evidence["channel_id"] == "UC-skeleton"
    assert pattern.evidence["sample_count"] == 5
    assert pattern.evidence["comparison_sample_count"] == 5
    assert pattern.evidence["winning_median"] in {0.02, 0.08, 0.6, 0.8, 200.0}
    assert pattern.evidence["comparison_median"] in {0.01, 0.04, 0.4, 100.0}
    assert pattern.evidence["relative_difference"] == pytest.approx(0.5) or pattern.evidence["relative_difference"] == pytest.approx(1.0)
    assert pattern.evidence["topic_scope"]
    assert pattern.evidence["format_scope"]
    assert pattern.evidence["comparison_period"] in {"2026-08-01/2026-08-28", "first 7 days"}
    assert pattern.confidence == "medium"
    assert str(pattern.evidence["sample_count"]) in pattern.summary


def test_unknown_non_finite_and_incomplete_groups_never_create_confident_patterns():
    videos = _videos(
        topic=lambda n: None if n < 5 else "unknown",
        format=lambda n: None if n < 5 else "unknown",
        views=lambda n: math.nan if n < 5 else math.inf,
        ctr=lambda n: math.nan if n < 5 else None,
        geography=lambda n: "" if n < 5 else None,
    )

    assert extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos)) == []


@pytest.mark.parametrize(
    ("field", "metric"),
    [
        ("thumbnail_wording", {"ctr": lambda n: .08 if n < 5 else .04}),
        ("hook_type", {"average_percentage_viewed": lambda n: .60 if n < 5 else .40}),
        ("geography", {"views": lambda n: 200 if n < 5 else 100}),
    ],
)
def test_unknown_text_labels_are_not_treated_as_evidence_groups(field, metric):
    videos = _videos(**{field: lambda n: "unknown" if n < 5 else "n/a", **metric})

    assert not any(
        pattern.pattern_type in {"thumbnail_wording", "hook_type", "geography"}
        for pattern in extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos))
    )


def test_metrics_from_different_or_unknown_analytics_periods_are_not_compared():
    videos = _videos(
        topic=lambda n: "Fishing" if n < 5 else "History",
        views=lambda n: 200 if n < 5 else 100,
        comparison_period=lambda n: "2026-08-01/2026-08-28" if n < 5 else None,
    )
    assert not any(
        pattern.pattern_type == "topic_performance"
        for pattern in extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos))
    )


def test_duplicate_video_ids_cannot_inflate_the_evidence_threshold():
    source = _videos(
        topic=lambda n: "Fishing" if n < 5 else "History",
        views=lambda n: 200 if n < 5 else 100,
    )
    duplicated = [replace(video, video_id=f"video-{number % 4}") for number, video in enumerate(source)]

    assert extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=duplicated)) == []


def _snapshot(number: int) -> VideoMetricSnapshot:
    fishing = number < 5
    return VideoMetricSnapshot(
        youtube_video_id=f"video-{number}",
        channel_id="UC-skeleton",
        captured_at=datetime(2026, 9, 8, tzinfo=UTC).replace(tzinfo=None),
        analytics_start_date=date(2026, 8, 1),
        analytics_end_date=date(2026, 8, 28),
        topic="Fishing" if fishing else "History",
        format="long",
        length_seconds=600,
        views=200 if fishing else 100,
    )


def test_rebuild_is_channel_gated_atomic_idempotent_and_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'learning.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([_snapshot(number) for number in range(10)])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        first = client.post("/learning/rebuild")
        second = client.post("/learning/rebuild")
        response = client.get("/learning/patterns")

    assert first.status_code == second.status_code == response.status_code == 200
    assert first.json() == second.json() == {"rebuilt": 1}
    assert response.json() == [{
        "id": 1,
        "topic": "All topics",
        "pattern_type": "topic_performance",
        "summary": "Fishing median views were 100.0% higher than comparable topics (5 vs 5 videos; long, 5-15m).",
        "confidence": "medium",
        "evidence_count": 5,
        "evidence": {
            "metric": "views",
            "channel_id": "UC-skeleton",
            "winning_group": "Fishing",
            "comparison_group": "History",
            "sample_count": 5,
            "winning_median": 200.0,
            "comparison_sample_count": 5,
            "comparison_median": 100.0,
            "relative_difference": 1.0,
            "topic_scope": "All topics",
            "format_scope": "long",
            "length_scope": "5-15m",
            "comparison_period": "2026-08-01/2026-08-28",
        },
    }]
    assert len(list(session.scalars(select(LearningPattern)))) == 1

    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-another-channel")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/learning/patterns").json() == []
    session.close()
    get_settings.cache_clear()


def test_read_skips_malformed_or_non_finite_persisted_evidence(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bad-evidence.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(LearningPattern(
        topic="Fishing",
        pattern_type="topic_performance",
        summary="Untrusted legacy row",
        evidence_json='{"metric":"views","winning_group":"Fishing","sample_count":5,"comparison_sample_count":5,"winning_median":NaN,"comparison_median":1,"relative_difference":1,"topic_scope":"Fishing","format_scope":"long","length_scope":"5-15m","comparison_period":"period"}',
        confidence="high",
    ))
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.get("/learning/patterns").json() == []

    session.close()


def test_rebuild_refuses_to_mix_unidentified_channel_data(tmp_path, monkeypatch):
    monkeypatch.delenv("EXPECTED_YOUTUBE_CHANNEL_ID", raising=False)
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'unscoped.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        response = client.post("/learning/rebuild")

    assert response.status_code == 503
    assert "EXPECTED_YOUTUBE_CHANNEL_ID" in response.json()["detail"]
    session.close()
    get_settings.cache_clear()


def test_rebuild_can_use_optional_learning_dimensions_persisted_with_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'persisted-dimensions.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    for number in range(10):
        snapshot = _snapshot(number)
        snapshot.topic = "Fishing"
        snapshot.views = None
        snapshot.thumbnail_wording = "mystery" if number < 5 else "plain"
        snapshot.ctr = .08 if number < 5 else .04
        session.add(snapshot)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.post("/learning/rebuild").json() == {"rebuilt": 1}
        assert client.get("/learning/patterns").json()[0]["pattern_type"] == "thumbnail_wording"

    session.close()
    get_settings.cache_clear()


def test_legacy_metric_schema_is_upgraded_with_optional_learning_dimensions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-learning.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE video_metric_snapshots ("
            "id INTEGER PRIMARY KEY, youtube_video_id VARCHAR(32), captured_at DATETIME)"
        )
        connection.exec_driver_sql(
            "INSERT INTO video_metric_snapshots VALUES (1, 'legacy-video', '2026-09-01 00:00:00')"
        )

    upgrade_video_metrics_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("video_metric_snapshots")}
    assert {"channel_id", "thumbnail_wording", "hook_type", "geography", "is_follow_up"} <= columns
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT channel_id FROM video_metric_snapshots").all() == [(None,)]


def test_follow_up_pattern_never_uses_short_form_evidence():
    videos = _videos(
        format="short",
        length_seconds=30,
        is_follow_up=lambda n: n < 5,
        views_7d=lambda n: 200 if n < 5 else 100,
    )

    assert not any(
        pattern.pattern_type == "follow_up_performance"
        for pattern in extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos))
    )


def test_latest_snapshot_prefers_newer_valid_reporting_period_over_capture_time(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'period-order.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    for number in range(10):
        newest_period = _snapshot(number)
        newest_period.id = number + 1
        newest_period.captured_at = datetime(2026, 9, 1)
        newest_period.analytics_end_date = date(2026, 8, 28)
        older_period_captured_later = _snapshot(number)
        older_period_captured_later.id = 100 + number
        older_period_captured_later.captured_at = datetime(2026, 9, 8)
        older_period_captured_later.analytics_start_date = date(2026, 7, 1)
        older_period_captured_later.analytics_end_date = date(2026, 7, 28)
        older_period_captured_later.topic = "Fishing"
        older_period_captured_later.views = 100
        session.add_all([newest_period, older_period_captured_later])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.post("/learning/rebuild").json() == {"rebuilt": 1}
        assert client.get("/learning/patterns").json()[0]["evidence"]["comparison_period"] == "2026-08-01/2026-08-28"

    session.close()
    get_settings.cache_clear()


def test_learning_rebuild_filters_snapshot_provenance_and_legacy_rows_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()


def test_explicit_metrics_are_attached_only_to_the_latest_reporting_period(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'annotation-period.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    older = _snapshot(1)
    older.analytics_start_date = date(2026, 7, 1)
    older.analytics_end_date = date(2026, 7, 28)
    newer = _snapshot(1)
    newer.analytics_end_date = date(2026, 8, 28)
    session.add_all([older, newer])
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.put("/learning/videos/video-1/metadata", json={"ctr": .08}).json() == {"updated": 1}

    session.expire_all()
    rows = list(session.scalars(select(VideoMetricSnapshot).order_by(VideoMetricSnapshot.analytics_end_date)))
    assert [row.ctr for row in rows] == [None, .08]
    session.close()
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'channel-provenance.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    rows = [_snapshot(number) for number in range(10)]
    for number, row in enumerate(rows):
        row.channel_id = None if number < 5 else "UC-other"
    session.add_all(rows)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.post("/learning/rebuild").json() == {"rebuilt": 0}

    session.close()
    get_settings.cache_clear()


class _SyncLearningClient:
    token_path = None

    @contextmanager
    def token_guard(self):
        yield

    def ensure_token_unchanged(self):
        return None

    def get_authenticated_channel(self):
        return ChannelIdentity("UC-skeleton", "Skeleton Coast Fishing Adventures & Tours", "UU-skeleton")

    def list_uploaded_videos(self, _playlist_id):
        published = datetime.now(UTC) - timedelta(days=30)
        return [UploadedVideo(f"video-{number}", f"Video {number}", published, 600, "long") for number in range(20)]

    def fetch_video_metrics(self, video_id, _start_date, _end_date):
        number = int(video_id.rsplit("-", 1)[1])
        better = number % 10 < 5
        fishing = number < 10
        views = (300 if better else 200) if fishing else (150 if better else 100)
        return RawVideoMetrics(
            video_id=video_id,
            views=views,
            average_percentage_viewed=60 if better else 40,
            subscribers_gained=round(views * (.02 if better else .01)),
            traffic_raw=(
                {"BROWSE": 80, "RELATED_VIDEO": 10, "YT_SEARCH": 10}
                if better else {"BROWSE": 1, "RELATED_VIDEO": 1, "YT_SEARCH": 98}
            ),
        )

    def fetch_video_views(self, video_id, _start_date, _end_date):
        number = int(video_id.rsplit("-", 1)[1])
        better = number % 10 < 5
        return (300 if better else 200) if number < 10 else (150 if better else 100)


def test_real_sync_provenance_and_explicit_annotations_feed_learning_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'sync-learning.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: _SyncLearningClient())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.post("/youtube/sync?start_date=2026-08-01&end_date=2026-09-08").status_code == 200
        for number in range(20):
            better = number % 10 < 5
            response = client.put(f"/learning/videos/video-{number}/metadata", json={
                "topic": "Fishing" if number < 10 else "History",
                "thumbnail_wording": "mystery" if better else "plain",
                "hook_type": "reveal" if better else "question",
                "geography": "Namibia" if better else "South Africa",
                "is_follow_up": better,
                "ctr": .08 if better else .04,
            })
            assert response.status_code == 200
        assert client.post("/youtube/sync?start_date=2026-08-01&end_date=2026-09-08").status_code == 200
        rebuild = client.post("/learning/rebuild")
        patterns = client.get("/learning/patterns").json()

    assert rebuild.status_code == 200
    assert {pattern["pattern_type"] for pattern in patterns} == {
        "thumbnail_wording", "hook_type", "topic_performance",
        "browse_suggested_response", "geography", "follow_up_performance",
    }
    snapshots = list(session.scalars(select(VideoMetricSnapshot)))
    assert {row.channel_id for row in snapshots} == {"UC-skeleton"}
    assert {row.views_7d for row in snapshots} == {100, 150, 200, 300}

    with TestClient(app) as client:
        for number in range(20):
            assert client.put(
                f"/learning/videos/video-{number}/metadata",
                json={"format": "long" if number % 10 < 5 else "short"},
            ).status_code == 200
        assert client.post("/learning/rebuild").status_code == 200
        assert "subscriber_conversion" in {
            pattern["pattern_type"] for pattern in client.get("/learning/patterns").json()
        }
    session.close()
    get_settings.cache_clear()


class _ShortSyncLearningClient(_SyncLearningClient):
    def list_uploaded_videos(self, _playlist_id):
        published = datetime.now(UTC) - timedelta(days=30)
        return [
            UploadedVideo(f"short-{number}", f"Short {number}", published, 20 if number < 5 else 50, "unknown")
            for number in range(10)
        ]

    def fetch_video_metrics(self, video_id, _start_date, _end_date):
        number = int(video_id.rsplit("-", 1)[1])
        return RawVideoMetrics(video_id=video_id, views=100, average_percentage_viewed=80 if number < 5 else 40)

    def fetch_video_views(self, _video_id, _start_date, _end_date):
        return 100


def test_synced_durations_and_explicit_format_support_short_duration_learning(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'short-learning.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(youtube_routes, "get_youtube_client", lambda: _ShortSyncLearningClient())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        assert client.post("/youtube/sync?start_date=2026-08-01&end_date=2026-09-08").status_code == 200
        for number in range(10):
            assert client.put(
                f"/learning/videos/short-{number}/metadata",
                json={"topic": "Fishing", "format": "short"},
            ).status_code == 200
        assert client.post("/learning/rebuild").status_code == 200
        assert "short_duration" in {
            pattern["pattern_type"] for pattern in client.get("/learning/patterns").json()
        }

    session.close()
    get_settings.cache_clear()
