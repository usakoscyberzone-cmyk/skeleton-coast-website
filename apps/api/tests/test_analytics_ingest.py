from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import VideoMetricSnapshot
from app.services.analytics_ingest import normalize_metrics, persist_metric_snapshot


def test_normalize_metrics_calculates_rates_and_converts_google_percentages_to_ratios():
    """Using raw Google percentages would inflate dashboard rates by 100x."""
    raw = {
        "video_id": "abc123",
        "views": 422,
        "impressions": 5000,
        "ctr": 7.1,
        "watch_minutes": 480.0,
        "avg_view_duration_seconds": 68.0,
        "average_percentage_viewed": 42.8,
        "subscribers_gained": 5,
        "returning_viewers": 120,
        "traffic": {
            "BROWSE": 57.6,
            "SUGGESTED": 4.0,
            "SEARCH": 8.0,
            "EXTERNAL": 27.0,
            "SHORTS": 0.0,
        },
        "retention": [{"elapsed_ratio": 0.5, "audience_retention": 75.0}],
        "views_1h": 31,
        "views_24h": 190,
        "views_7d": 410,
    }

    result = normalize_metrics(raw)

    assert result.subscriber_conversion_rate == 5 / 422
    assert result.ctr == 0.071
    assert result.average_percentage_viewed == 0.428
    assert result.browse_share == 0.576
    assert result.returning_viewers == 120
    assert result.retention == [{"elapsed_ratio": 0.5, "audience_retention": 0.75}]
    assert (result.views_1h, result.views_24h, result.views_7d) == (31, 190, 410)


def test_normalize_metrics_keeps_unavailable_values_null_and_does_not_divide_by_zero():
    """Replacing absent API metrics with zero would invent performance evidence."""
    result = normalize_metrics({"video_id": "abc123", "views": 0, "traffic": {}})

    assert result.impressions is None
    assert result.ctr is None
    assert result.subscriber_conversion_rate is None
    assert result.browse_share is None
    assert result.returning_viewers is None
    assert result.retention is None


def test_persist_metric_snapshot_is_idempotent_for_the_same_video_and_reporting_period(tmp_path):
    """Appending duplicates on retry would distort every summary and recommendation."""
    engine = create_engine(f"sqlite:///{tmp_path / 'analytics.db'}")
    Base.metadata.create_all(engine)
    metric = normalize_metrics({"video_id": "abc123", "views": 422, "returning_viewers": 19})

    with Session(engine) as session:
        persist_metric_snapshot(session, metric, start_date=date(2026, 9, 1), end_date=date(2026, 9, 6))
        persist_metric_snapshot(session, metric, start_date=date(2026, 9, 1), end_date=date(2026, 9, 6))
        session.commit()
        snapshots = list(session.scalars(select(VideoMetricSnapshot)))

    assert len(snapshots) == 1
    assert snapshots[0].returning_viewers == 19
    assert snapshots[0].analytics_start_date == date(2026, 9, 1)
