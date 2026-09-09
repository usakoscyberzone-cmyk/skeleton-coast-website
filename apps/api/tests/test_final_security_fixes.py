from datetime import UTC, datetime, timedelta
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import _canonical_windows_path, get_settings, require_master_project_folder
from app.db import Base, get_session, upgrade_recommendations_schema
from app.main import create_app
from app.models import Project, Recommendation, VideoMetricSnapshot
from app.routes.recommendations import active_recommendations
from app.services.analytics_ingest import normalize_metrics, persist_metric_snapshot
from app.services.learning_library import ChannelDataset, ChannelVideo, extract_learning_patterns


def _app_with_session(tmp_path: Path, monkeypatch, channel_id: str | None = "UC-skeleton"):
    if channel_id is None:
        monkeypatch.delenv("EXPECTED_YOUTUBE_CHANNEL_ID", raising=False)
    else:
        monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", channel_id)
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'final-fixes.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return app, session


def _snapshot(channel_id: str | None, video_id: str, views: float = 10, **values):
    now = datetime.now(UTC).replace(tzinfo=None)
    defaults = dict(
        channel_id=channel_id,
        youtube_video_id=video_id,
        captured_at=now,
        published_at=now.replace(tzinfo=UTC) - timedelta(hours=24),
        analytics_start_date=now.date(),
        analytics_end_date=now.date(),
        topic="Fishing",
        format="long",
        length_seconds=600,
        impressions=2000,
        views=views,
        ctr=.05,
        average_percentage_viewed=.5,
        browse_share=.4,
        suggested_share=.2,
        external_share=.1,
    )
    defaults.update(values)
    return VideoMetricSnapshot(**defaults)


def test_api_rejects_arbitrary_master_root_before_scanning_or_creating(tmp_path, monkeypatch):
    arbitrary = tmp_path / "YouTube Projects"
    project = arbitrary / "Must Not Be Touched"
    project.mkdir(parents=True)
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(arbitrary))
    get_settings.cache_clear()
    app, session = _app_with_session(tmp_path, monkeypatch)

    response = TestClient(app).post("/projects/scan")

    assert response.status_code == 503
    assert r"I:\YouTube Projects" in response.json()["detail"]
    assert list(project.iterdir()) == []
    session.close()


def test_master_root_comparison_is_windows_canonical_and_case_insensitive():
    assert _canonical_windows_path(r"i:\YOUTUBE PROJECTS\.") == _canonical_windows_path(
        r"I:\YouTube Projects"
    )


def test_tests_can_inject_master_capability_without_production_environment_bypass(tmp_path, monkeypatch):
    master = tmp_path / "YouTube Projects"
    (master / "Project").mkdir(parents=True)
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(master))
    get_settings.cache_clear()
    app, session = _app_with_session(tmp_path, monkeypatch)
    app.dependency_overrides[require_master_project_folder] = lambda: master

    response = TestClient(app).post("/projects/scan")

    assert response.status_code == 200
    assert {item.name for item in (master / "Project").iterdir()} == {
        "Analytics", "Captions", "Exports", "Metadata", "Shorts", "Thumbnails"
    }
    session.close()


def test_summary_and_retention_fail_closed_to_configured_channel(tmp_path, monkeypatch):
    app, session = _app_with_session(tmp_path, monkeypatch)
    session.add_all([
        _snapshot("UC-skeleton", "ours", views=11, retention_json='[{"elapsed_ratio":0,"audience_retention":1}]'),
        _snapshot("UC-other", "theirs", views=999, retention_json='[{"elapsed_ratio":0,"audience_retention":1}]'),
        _snapshot(None, "legacy", views=777),
    ])
    session.commit()
    client = TestClient(app)

    summary = client.get("/analytics/summary")
    ours = client.get("/analytics/videos/ours/retention")
    theirs = client.get("/analytics/videos/theirs/retention")

    assert summary.status_code == 200
    assert summary.json()["video_count"] == 1
    assert summary.json()["views"] == {"value": 11, "coverage": 1}
    assert ours.status_code == 200
    assert theirs.status_code == 404
    session.close()


def test_recommendations_never_deactivate_or_surface_another_channel(tmp_path, monkeypatch):
    app, session = _app_with_session(tmp_path, monkeypatch)
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add_all([
        _snapshot("UC-skeleton", "ours", views=100),
        _snapshot("UC-other", "theirs", views=999),
        _snapshot(None, "legacy", views=777),
        Recommendation(channel_id="UC-other", youtube_video_id="theirs", state="green", action="other", reason="other", confidence="high", data_used_json="{}", is_active=True),
        Recommendation(channel_id=None, youtube_video_id="legacy", state="green", action="legacy", reason="legacy", confidence="high", data_used_json="{}", is_active=True),
    ])
    session.commit()
    client = TestClient(app)

    assert client.post("/recommendations/rebuild").json() == {"rebuilt": 1}
    visible = client.get("/recommendations/active")

    assert visible.status_code == 200
    assert [row["youtube_video_id"] for row in visible.json()] == ["ours"]
    other = session.scalar(select(Recommendation).where(Recommendation.channel_id == "UC-other"))
    legacy = session.scalar(select(Recommendation).where(Recommendation.channel_id.is_(None)))
    assert other.is_active is True
    assert legacy.is_active is True
    session.close()


def test_active_recommendations_sanitize_nonfinite_legacy_evidence(tmp_path, monkeypatch):
    app, session = _app_with_session(tmp_path, monkeypatch)
    session.add(Recommendation(
        channel_id="UC-skeleton", youtube_video_id="ours", state="amber",
        action="wait", reason="legacy", confidence="low",
        data_used_json='{"ctr": NaN, "nested": {"trend": Infinity}}', is_active=True,
    ))
    session.commit()

    response = TestClient(app, raise_server_exceptions=False).get("/recommendations/active")
    direct = active_recommendations(session, channel_id="UC-skeleton")

    assert response.status_code == 200
    assert response.json()[0]["data_used"] == {"ctr": None, "nested": {"trend": None}}
    assert direct[0]["data_used"] == {"ctr": None, "nested": {"trend": None}}
    assert "NaN" not in response.text and "Infinity" not in response.text
    session.close()


@pytest.mark.parametrize("channel_id", [None, "UC-switched"])
def test_channel_configuration_is_required_and_switches_visibility(tmp_path, monkeypatch, channel_id):
    app, session = _app_with_session(tmp_path, monkeypatch, channel_id)
    session.add(Recommendation(channel_id="UC-skeleton", youtube_video_id="ours", state="green", action="ours", reason="ours", confidence="high", data_used_json="{}", is_active=True))
    session.commit()
    response = TestClient(app).get("/recommendations/active")
    if channel_id is None:
        assert response.status_code == 503
        assert "EXPECTED_YOUTUBE_CHANNEL_ID" in response.json()["detail"]
    else:
        assert response.status_code == 200
        assert response.json() == []
    session.close()


def test_recommendation_migration_adds_provenance_and_deactivates_legacy_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-recommendations.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE recommendations (id INTEGER PRIMARY KEY, youtube_video_id TEXT NOT NULL, state TEXT, action TEXT, reason TEXT, confidence TEXT, data_used_json TEXT, is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO recommendations VALUES (1, 'v', 'green', 'a', 'r', 'high', '{}', 1, CURRENT_TIMESTAMP)")

    upgrade_recommendations_schema(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(recommendations)")}
        row = connection.exec_driver_sql("SELECT channel_id, is_active FROM recommendations").one()
    assert "channel_id" in columns
    assert row == (None, 0)


def test_snapshot_provenance_cannot_be_attached_to_a_legacy_row(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'provenance.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        legacy = normalize_metrics({"video_id": "v", "views": 1})
        persist_metric_snapshot(session, legacy, start_date=datetime.now().date(), end_date=datetime.now().date())
        session.commit()
        current = normalize_metrics({"video_id": "v", "channel_id": "UC-skeleton", "views": 2})
        with pytest.raises(ValueError, match="provenance is immutable"):
            persist_metric_snapshot(session, current, start_date=datetime.now().date(), end_date=datetime.now().date())


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_normalize_metrics_nulls_all_nonfinite_numeric_inputs_and_derivations(bad):
    metric = normalize_metrics({
        "video_id": "v", "views": bad, "impressions": bad, "ctr": bad,
        "watch_minutes": bad, "avg_view_duration_seconds": bad,
        "average_percentage_viewed": bad, "subscribers_gained": bad,
        "returning_viewers": bad, "duration_seconds": bad, "length_seconds": bad,
        "views_1h": bad, "views_24h": bad, "views_7d": bad,
        "traffic": {"BROWSE": bad, "SUGGESTED": .2},
        "retention": [{"elapsed_ratio": bad, "audience_retention": bad}],
    })
    numeric = (
        metric.views, metric.impressions, metric.ctr, metric.watch_minutes,
        metric.avg_view_duration_seconds, metric.average_percentage_viewed,
        metric.subscribers_gained, metric.subscriber_conversion_rate,
        metric.browse_share, metric.returning_viewers, metric.duration_seconds,
        metric.length_seconds, metric.views_1h, metric.views_24h, metric.views_7d,
    )
    assert all(value is None for value in numeric)
    assert metric.retention is None


def test_normalize_metrics_nulls_finite_values_outside_metric_domains():
    metric = normalize_metrics({
        "video_id": "v", "views": -1, "impressions": -1,
        "watch_minutes": -1, "avg_view_duration_seconds": -1,
        "average_percentage_viewed": 101, "subscribers_gained": -1,
        "returning_viewers": -1, "duration_seconds": -1, "views_1h": -1,
        "traffic": {"BROWSE": 1.2},
        "retention": [{"elapsed_ratio": 1.1, "audience_retention": 1}],
    })
    assert metric.views is None
    assert metric.impressions is None
    assert metric.watch_minutes is None
    assert metric.avg_view_duration_seconds is None
    assert metric.average_percentage_viewed is None
    assert metric.subscribers_gained is None
    assert metric.returning_viewers is None
    assert metric.duration_seconds is None
    assert metric.views_1h is None
    assert metric.browse_share is None
    assert metric.retention is None


def test_normalize_metrics_nulls_impossible_derived_subscriber_ratio():
    metric = normalize_metrics({"video_id": "v", "views": 1, "subscribers_gained": 2})

    assert metric.subscriber_conversion_rate is None


def test_learning_extraction_rejects_out_of_range_ratio_evidence():
    videos = [
        ChannelVideo(
            video_id=f"v-{group}-{number}", topic="Fishing", format="long",
            length_seconds=600, comparison_period="2026-08-01/2026-08-28",
            thumbnail_wording=group, ctr=value,
        )
        for group, value in (("winner", 2.0), ("comparison", 1.5))
        for number in range(5)
    ]

    patterns = extract_learning_patterns(ChannelDataset(channel_id="UC-skeleton", videos=videos))

    assert not [pattern for pattern in patterns if pattern.pattern_type == "thumbnail_wording"]


def test_summary_ignores_nonfinite_legacy_rows_and_emits_strict_json(tmp_path, monkeypatch):
    app, session = _app_with_session(tmp_path, monkeypatch)
    session.add_all([
        _snapshot("UC-skeleton", "finite", views=10, ctr=.1),
        _snapshot("UC-skeleton", "nan", views=math.nan, ctr=math.inf, browse_share=-math.inf),
    ])
    session.commit()

    response = TestClient(app, raise_server_exceptions=False).get("/analytics/summary")

    assert response.status_code == 200
    assert response.json()["views"] == {"value": 10, "coverage": 1}
    assert "NaN" not in response.text and "Infinity" not in response.text
    session.close()


def test_summary_ignores_legacy_values_outside_count_and_ratio_domains(tmp_path, monkeypatch):
    app, session = _app_with_session(tmp_path, monkeypatch)
    session.add_all([
        _snapshot("UC-skeleton", "finite", views=10, impressions=100, ctr=.1,
                  average_percentage_viewed=.5, subscribers_gained=1),
        _snapshot("UC-skeleton", "invalid", views=10.5, impressions=-2, ctr=1.2,
                  average_percentage_viewed=-.1, subscribers_gained=-1,
                  browse_share=1.1),
    ])
    session.commit()

    response = TestClient(app).get("/analytics/summary")

    assert response.json()["views"] == {"value": 10, "coverage": 1}
    assert response.json()["impressions"] == {"value": 100, "coverage": 1}
    assert response.json()["ctr"] == {"value": .1, "coverage": 1}
    assert response.json()["average_percentage_viewed"] == {"value": .5, "coverage": 1}
    assert response.json()["subscriber_conversion_rate"] == {"value": .1, "coverage": 1}
    session.close()
