from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import VideoMetricSnapshot
from app.routes.youtube import analytics_summary


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
