from app.services.youtube_client import RawVideoMetrics


def test_raw_metrics_is_typed_and_unsupported_values_stay_null():
    raw = RawVideoMetrics(video_id="v1")
    assert raw.impressions is None
    assert raw.ctr is None
    assert raw.returning_viewers is None
