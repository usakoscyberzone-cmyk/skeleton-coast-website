from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, get_session
from app.config import require_expected_youtube_channel_id
from app.main import create_app
from app.models import Recommendation, VideoMetricSnapshot


def _client_with_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recommendations.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_expected_youtube_channel_id] = lambda: "UC-skeleton"
    return TestClient(app), session


def _snapshot(video_id, captured_at, **values):
    defaults = dict(
        channel_id="UC-skeleton", youtube_video_id=video_id, captured_at=captured_at,
        analytics_start_date=captured_at.date(), analytics_end_date=captured_at.date(),
        published_at=captured_at.replace(tzinfo=UTC) - timedelta(hours=20),
        topic="Fishing", format="long", length_seconds=600,
        impressions=2_000, views=100, ctr=.03, average_percentage_viewed=.30,
        browse_share=.20, suggested_share=.20, external_share=.10,
    )
    defaults.update(values)
    return VideoMetricSnapshot(**defaults)


def test_rebuild_uses_latest_snapshot_and_is_idempotent_with_one_active_row_per_video(tmp_path):
    client, session = _client_with_session(tmp_path)
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add_all([
        _snapshot("current", now - timedelta(days=1), ctr=.90, average_percentage_viewed=.90),
        _snapshot("current", now, ctr=.03, average_percentage_viewed=.30),
        *[_snapshot(f"peer-{number}", now, ctr=.07, average_percentage_viewed=.50) for number in range(5)],
    ])
    session.commit()

    first = client.post("/recommendations/rebuild")
    second = client.post("/recommendations/rebuild")
    active = client.get("/recommendations/active")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {"rebuilt": 6}
    payload = active.json()
    assert len(payload) == 6
    current = next(row for row in payload if row["youtube_video_id"] == "current")
    assert current["state"] == "red"
    assert {"id", "youtube_video_id", "state", "action", "reason", "confidence", "data_used"} <= current.keys()
    assert len(list(session.scalars(select(Recommendation).where(Recommendation.youtube_video_id == "current", Recommendation.is_active.is_(True))))) == 1


def test_active_endpoint_returns_empty_list_when_no_recommendations_exist(tmp_path):
    client, session = _client_with_session(tmp_path)
    assert client.get("/recommendations/active").status_code == 200
    assert client.get("/recommendations/active").json() == []
    session.close()


def test_rebuild_with_normal_ingested_snapshots_missing_topic_stays_non_comparative_amber(tmp_path):
    client, session = _client_with_session(tmp_path)
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add_all([
        _snapshot("target", now - timedelta(days=1), ctr=.90, average_percentage_viewed=.90),
        _snapshot("target", now, ctr=.03, average_percentage_viewed=.30),
        *[_snapshot(f"peer-{number}", now, ctr=.07, average_percentage_viewed=.50) for number in range(5)],
    ])
    for snapshot in session.scalars(select(VideoMetricSnapshot)):
        snapshot.topic = None
    session.commit()

    assert client.post("/recommendations/rebuild").status_code == 200
    target = next(row for row in client.get("/recommendations/active").json() if row["youtube_video_id"] == "target")
    assert target["state"] == "amber"
    assert target["confidence"] == "low"
    assert target["data_used"]["comparable_sample_size"] == 0


def test_rebuild_with_missing_duration_stays_non_comparative_amber(tmp_path):
    client, session = _client_with_session(tmp_path)
    now = datetime.now(UTC).replace(tzinfo=None)
    snapshots = [
        _snapshot("target", now - timedelta(days=1), ctr=.90, average_percentage_viewed=.90),
        _snapshot("target", now, ctr=.03, average_percentage_viewed=.30),
        *[_snapshot(f"peer-{number}", now, ctr=.07, average_percentage_viewed=.50) for number in range(5)],
    ]
    for snapshot in snapshots:
        snapshot.length_seconds = None
        snapshot.duration_seconds = None
    session.add_all(snapshots)
    session.commit()

    assert client.post("/recommendations/rebuild").status_code == 200
    target = next(row for row in client.get("/recommendations/active").json() if row["youtube_video_id"] == "target")
    assert target["state"] == "amber"
    assert target["confidence"] == "low"
    assert target["data_used"]["comparable_sample_size"] == 0
