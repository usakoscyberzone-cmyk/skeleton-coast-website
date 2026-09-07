from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import VideoMetricSnapshot
from app.routes.youtube import analytics_summary, retention_data


def test_summary_returns_latest_leaders_and_view_weighted_available_traffic_ratios(tmp_path):
    """A stale snapshot or unweighted traffic average would choose the wrong dashboard evidence."""
    engine = create_engine(f"sqlite:///{tmp_path / 'summary.db'}")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        session.add_all([
            VideoMetricSnapshot(youtube_video_id="long-new", title="Old leader", video_type="long", views=900, captured_at=now - timedelta(days=1), analytics_end_date=date(2026, 9, 5)),
            VideoMetricSnapshot(youtube_video_id="long-new", title="Current leader", video_type="long", views=600, captured_at=now, analytics_end_date=date(2026, 9, 6), browse_share=.50, suggested_share=.25),
            VideoMetricSnapshot(youtube_video_id="short-new", title="Current Short", format="short", views=200, captured_at=now, browse_share=.20, suggested_share=.50, search_share=.10),
            VideoMetricSnapshot(youtube_video_id="unknown-traffic", title="No traffic", video_type="long", views=100, captured_at=now, browse_share=None),
        ])
        session.commit()

        summary = analytics_summary(session)

    assert summary["top_long_form"] == {"id": "long-new", "title": "Current leader", "views": 600}
    assert summary["top_short"] == {"id": "short-new", "title": "Current Short", "views": 200}
    assert summary["traffic_sources"] == {
        "Browse": 0.425,
        "Suggested": 0.3125,
        "Search": 0.1,
    }


def test_summary_returns_null_leaders_and_empty_traffic_without_available_evidence(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'summary-empty.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(VideoMetricSnapshot(youtube_video_id="unknown", views=None))
        session.commit()
        summary = analytics_summary(session)

    assert summary["top_long_form"] is None
    assert summary["top_short"] is None
    assert summary["traffic_sources"] == {}


def test_summary_exposes_persisted_metrics_video_choices_and_all_required_topics(tmp_path):
    """A dashboard screen must distinguish stored evidence from unavailable fields."""
    engine = create_engine(f"sqlite:///{tmp_path / 'summary-details.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(VideoMetricSnapshot(
            youtube_video_id="fishing-video", title="Fishing evidence", topic="Fishing", views=10,
            impressions=100, ctr=.1, avg_view_duration_seconds=20, average_percentage_viewed=.5,
            subscriber_conversion_rate=.02, returning_viewers=3, views_1h=4, views_24h=8,
            views_7d=10, browse_share=.4,
        ))
        session.commit()
        summary = analytics_summary(session)

    assert summary["impressions"] == {"value": 100, "coverage": 1}
    assert summary["avg_view_duration_seconds"] == {"value": 20, "coverage": 1}
    assert summary["traffic_source_coverage"] == {"Browse": 1}
    assert summary["videos"] == [{"id": "fishing-video", "title": "Fishing evidence", "views": 10}]
    assert summary["topics"]["Fishing"] == {"value": 10, "coverage": 1}
    assert summary["topics"]["Namibia travel"] == {"value": None, "coverage": 0}


def test_summary_weights_ratio_metrics_and_excludes_missing_or_zero_denominators(tmp_path):
    """Summing percentages or durations is false; each must use its persisted denominator."""
    engine = create_engine(f"sqlite:///{tmp_path / 'summary-weighted.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            VideoMetricSnapshot(youtube_video_id="small", views=100, impressions=100, ctr=.10,
                                avg_view_duration_seconds=60, average_percentage_viewed=.30,
                                subscribers_gained=10),
            VideoMetricSnapshot(youtube_video_id="large", views=900, impressions=900, ctr=.20,
                                avg_view_duration_seconds=120, average_percentage_viewed=.60,
                                subscribers_gained=90),
            VideoMetricSnapshot(youtube_video_id="missing", views=None, impressions=None, ctr=.90,
                                avg_view_duration_seconds=999, average_percentage_viewed=.99,
                                subscribers_gained=999),
            VideoMetricSnapshot(youtube_video_id="zero", views=0, impressions=0, ctr=.80,
                                avg_view_duration_seconds=333, average_percentage_viewed=.80,
                                subscribers_gained=50),
        ])
        session.commit()
        summary = analytics_summary(session)

    assert summary["ctr"] == {"value": .19, "coverage": 2}
    assert summary["avg_view_duration_seconds"] == {"value": 114, "coverage": 2}
    assert summary["average_percentage_viewed"] == {"value": .57, "coverage": 2}
    assert summary["subscriber_conversion_rate"] == {"value": .1, "coverage": 2}
    assert summary["views"] == {"value": 1000, "coverage": 3}
    assert summary["impressions"] == {"value": 1000, "coverage": 3}


def test_summary_lists_latest_retention_videos_even_without_views(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'summary-retention-videos.db'}")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        session.add_all([
            VideoMetricSnapshot(youtube_video_id="same", title="Old", views=1, retention_json='[{"elapsed_ratio": 0, "audience_retention": 1}]', analytics_end_date=date(2026, 9, 5), captured_at=now - timedelta(days=1)),
            VideoMetricSnapshot(youtube_video_id="same", title="Current", views=1, retention_json='[{"elapsed_ratio": 0, "audience_retention": 1}]', analytics_end_date=date(2026, 9, 6), captured_at=now),
            VideoMetricSnapshot(youtube_video_id="no-views", title="Retention only", views=None, retention_json='[{"elapsed_ratio": 0, "audience_retention": 1}]', captured_at=now),
            VideoMetricSnapshot(youtube_video_id="empty", retention_json='[]', captured_at=now),
        ])
        session.commit()
        summary = analytics_summary(session)

    assert summary["retention_videos"] == [
        {"id": "no-views", "title": "Retention only"},
        {"id": "same", "title": "Current"},
    ]


def test_retention_reads_share_one_normalized_validator_and_hide_corrupt_legacy_rows(tmp_path):
    """Only a non-empty array of numeric normalized points is selectable or readable."""
    engine = create_engine(f"sqlite:///{tmp_path / 'summary-retention-corrupt.db'}")
    Base.metadata.create_all(engine)
    malformed = {
        "bad-json": "{",
        "object": '{"elapsed_ratio": 0, "audience_retention": 1}',
        "empty": "[]",
        "wrong-key": '[{"elapsed_ratio": 0, "retention": 1}]',
        "non-numeric": '[{"elapsed_ratio": "zero", "audience_retention": 1}]',
        "sparse": '[{"elapsed_ratio": 0}]',
    }
    with Session(engine) as session:
        session.add(VideoMetricSnapshot(youtube_video_id="valid", title="Valid", retention_json='[{"elapsed_ratio": 0, "audience_retention": 1}]'))
        session.add_all(VideoMetricSnapshot(youtube_video_id=video_id, retention_json=payload) for video_id, payload in malformed.items())
        session.commit()
        summary = analytics_summary(session)
        values = {video_id: retention_data(video_id, session)["retention"] for video_id in malformed}
        valid = retention_data("valid", session)["retention"]

    assert summary["retention_videos"] == [{"id": "valid", "title": "Valid"}]
    assert values == {video_id: None for video_id in malformed}
    assert valid == [{"elapsed_ratio": 0, "audience_retention": 1}]
