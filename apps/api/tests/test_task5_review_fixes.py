from datetime import UTC, datetime

import pytest

from app.services.analytics_ingest import normalize_metrics
from app.services.youtube_client import RawVideoMetrics, YouTubeApiError, YouTubeClient


def test_raw_metrics_is_typed_and_unsupported_values_stay_null():
    raw = RawVideoMetrics(video_id="v1")
    assert raw.impressions is None
    assert raw.ctr is None
    assert raw.returning_viewers is None


def test_normalization_keeps_published_utc_and_rejects_invalid_ctr_input():
    with pytest.raises(ValueError, match="CTR"):
        normalize_metrics({"video_id": "v1", "ctr": 1.005})
    snapshot = normalize_metrics({"video_id": "v1", "published_at": datetime(2026, 9, 1, tzinfo=UTC)})
    assert snapshot.published_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_public_normalizer_keeps_already_normalized_ctr_and_traffic_fixture():
    snapshot = normalize_metrics({"video_id": "abc", "views": 422, "ctr": 0.071, "subscribers_gained": 5, "traffic": {"BROWSE": 0.576, "SUGGESTED": 0.04, "SEARCH": 0.08, "EXTERNAL": 0.27, "SHORTS": 0.0}})
    assert snapshot.ctr == 0.071
    assert snapshot.browse_share == 0.576
    assert snapshot.subscriber_conversion_rate == 5 / 422
