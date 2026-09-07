from dataclasses import dataclass

from app.services.baselines import build_channel_baseline, length_bucket


@dataclass
class Video:
    topic: str
    format: str
    length_seconds: int
    ctr: float | None
    average_percentage_viewed: float | None


def test_length_bucket_boundaries():
    assert [length_bucket(value) for value in (0, 59, 60, 300, 301, 900, 901)] == ["<1m", "<1m", "1-5m", "1-5m", "5-15m", "5-15m", "15m+"]


def test_missing_length_is_unknown_and_cannot_be_compared_as_a_short_video():
    assert length_bucket(None) == "unknown"


def test_baseline_uses_only_matching_topic_format_and_length_and_medians():
    videos = [Video("Fishing", "long", 600, ctr, retention) for ctr, retention in [(0.02, .2), (.04, .4), (.06, .6), (.08, .8), (.10, 1.0)]]
    videos += [Video("Angola", "long", 600, .99, .99), Video("Fishing", "short", 600, .99, .99), Video("Fishing", "long", 30, .99, .99)]
    baseline = build_channel_baseline("Fishing", "long", "5-15m", videos)
    assert baseline.sample_size == 5
    assert baseline.ctr == .06
    assert baseline.retention == .6
    assert baseline.confidence == "high"


def test_under_five_matches_has_low_confidence_and_no_comparative_medians():
    videos = [Video("Fishing", "long", 600, .08, .50) for _ in range(4)]
    baseline = build_channel_baseline("Fishing", "long", "5-15m", videos)
    assert baseline.sample_size == 4
    assert baseline.confidence == "low"
    assert baseline.ctr is None
    assert baseline.retention is None
