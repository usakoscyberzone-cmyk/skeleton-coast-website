"""Evidence-gated patterns learned only from one channel's stored history."""

from dataclasses import dataclass
import math
from statistics import median
from typing import Callable, Literal, Sequence

from .baselines import RECOGNIZED_FORMATS, RECOGNIZED_TOPICS, length_bucket


Confidence = Literal["medium", "high"]
PATTERN_TYPES = {
    "thumbnail_wording", "hook_type", "topic_performance", "short_duration",
    "subscriber_conversion", "browse_suggested_response", "geography", "follow_up_performance",
}


@dataclass(frozen=True)
class ChannelVideo:
    video_id: str
    topic: str | None = None
    format: str | None = None
    length_seconds: int | None = None
    views: float | None = None
    views_7d: float | None = None
    ctr: float | None = None
    average_percentage_viewed: float | None = None
    subscriber_conversion_rate: float | None = None
    browse_share: float | None = None
    suggested_share: float | None = None
    thumbnail_wording: str | None = None
    hook_type: str | None = None
    geography: str | None = None
    is_follow_up: bool | None = None
    comparison_period: str | None = None


@dataclass(frozen=True)
class ChannelDataset:
    channel_id: str
    videos: Sequence[ChannelVideo]


@dataclass(frozen=True)
class LearningPatternInput:
    topic: str
    pattern_type: str
    summary: str
    evidence: dict[str, str | int | float]
    confidence: Confidence


@dataclass(frozen=True)
class _PatternSpec:
    pattern_type: str
    metric_name: str
    metric_label: str
    dimension_label: str
    group: Callable[[ChannelVideo], str | None]
    metric: Callable[[ChannelVideo], float | int | None]
    scope: Callable[[ChannelVideo], tuple[str, str, str, str] | None]


def extract_learning_patterns(dataset: ChannelDataset) -> list[LearningPatternInput]:
    """Return stable comparative claims; unknown data can never become evidence."""
    if not isinstance(dataset.channel_id, str) or not dataset.channel_id.strip():
        return []
    id_counts: dict[str, int] = {}
    for video in dataset.videos:
        if isinstance(video.video_id, str) and video.video_id.strip():
            id_counts[video.video_id] = id_counts.get(video.video_id, 0) + 1
    unique_videos = [
        video for video in dataset.videos
        if isinstance(video.video_id, str) and video.video_id.strip() and id_counts[video.video_id] == 1
    ]
    patterns: list[LearningPatternInput] = []
    for spec in _SPECS:
        patterns.extend(_extract_spec(unique_videos, spec, dataset.channel_id.strip()))
    return sorted(
        patterns,
        key=lambda item: (item.pattern_type, item.topic.casefold(), item.evidence["format_scope"], item.evidence["length_scope"], item.evidence["comparison_period"]),
    )


def _extract_spec(videos: Sequence[ChannelVideo], spec: _PatternSpec, channel_id: str) -> list[LearningPatternInput]:
    cohorts: dict[tuple[str, str, str, str], dict[str, list[float]]] = {}
    display_names: dict[tuple[tuple[str, str, str, str], str], str] = {}
    for video in videos:
        scope = spec.scope(video)
        group = spec.group(video)
        value = _finite_non_negative(spec.metric(video))
        if scope is None or group is None or value is None:
            continue
        normalized_group = group.strip().casefold()
        if not normalized_group:
            continue
        cohorts.setdefault(scope, {}).setdefault(normalized_group, []).append(value)
        display_names.setdefault((scope, normalized_group), group.strip())

    results = []
    for scope in sorted(cohorts, key=lambda item: tuple(part.casefold() for part in item)):
        eligible = [
            (median(values), group, values)
            for group, values in cohorts[scope].items()
            if len(values) >= 5
        ]
        if len(eligible) < 2:
            continue
        eligible.sort(key=lambda item: (-item[0], item[1]))
        winner_median, winner_group, winner_values = eligible[0]
        comparison_median, comparison_group, comparison_values = eligible[1]
        if comparison_median <= 0 or winner_median <= comparison_median:
            continue
        relative_difference = (winner_median - comparison_median) / comparison_median
        topic_scope, format_scope, length_scope, comparison_period = scope
        winner_name = display_names[(scope, winner_group)]
        sample_count = len(winner_values)
        comparison_count = len(comparison_values)
        confidence: Confidence = "high" if min(sample_count, comparison_count) >= 10 else "medium"
        evidence: dict[str, str | int | float] = {
            "metric": spec.metric_name,
            "channel_id": channel_id,
            "winning_group": winner_name,
            "comparison_group": display_names[(scope, comparison_group)],
            "sample_count": sample_count,
            "winning_median": float(winner_median),
            "comparison_sample_count": comparison_count,
            "comparison_median": float(comparison_median),
            "relative_difference": float(relative_difference),
            "topic_scope": topic_scope,
            "format_scope": format_scope,
            "length_scope": length_scope,
            "comparison_period": comparison_period,
        }
        results.append(LearningPatternInput(
            topic=topic_scope,
            pattern_type=spec.pattern_type,
            summary=(
                f"{winner_name} median {spec.metric_label} were {relative_difference * 100:.1f}% higher "
                f"than comparable {spec.dimension_label} ({sample_count} vs {comparison_count} videos; "
                f"{format_scope}, {length_scope})."
            ),
            evidence=evidence,
            confidence=confidence,
        ))
    return results


def _finite_non_negative(value: float | int | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _finite_ratio(value: float | int | None) -> float | None:
    number = _finite_non_negative(value)
    return number if number is not None and number <= 1 else None


def _recognized(value: str | None, choices: set[str]) -> str | None:
    if not isinstance(value, str) or value.strip().casefold() not in choices:
        return None
    return value.strip()


def _normal_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    topic = _recognized(video.topic, RECOGNIZED_TOPICS)
    format_name = _recognized(video.format, RECOGNIZED_FORMATS)
    bucket = length_bucket(video.length_seconds)
    period = _text(video.comparison_period)
    if topic is None or format_name is None or bucket == "unknown" or period is None:
        return None
    return topic, format_name.casefold(), bucket, period


def _topic_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    format_name = _recognized(video.format, RECOGNIZED_FORMATS)
    topic = _recognized(video.topic, RECOGNIZED_TOPICS)
    bucket = length_bucket(video.length_seconds)
    period = _text(video.comparison_period)
    if topic is None or format_name is None or bucket == "unknown" or period is None:
        return None
    return "All topics", format_name.casefold(), bucket, period


def _subscriber_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    topic = _recognized(video.topic, RECOGNIZED_TOPICS)
    format_name = _recognized(video.format, RECOGNIZED_FORMATS)
    period = _text(video.comparison_period)
    if topic is None or format_name is None or period is None:
        return None
    return topic, "all formats", "all lengths", period


def _short_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    topic = _recognized(video.topic, RECOGNIZED_TOPICS)
    format_name = _recognized(video.format, RECOGNIZED_FORMATS)
    period = _text(video.comparison_period)
    if topic is None or format_name is None or format_name.casefold() != "short" or period is None:
        return None
    return topic, "short", "under 60s", period


def _fixed_7d_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    scope = _normal_scope_without_period(video)
    return (*scope, "first 7 days") if scope is not None else None


def _long_form_7d_scope(video: ChannelVideo) -> tuple[str, str, str, str] | None:
    scope = _normal_scope_without_period(video)
    if scope is None or scope[1] != "long":
        return None
    return (*scope, "first 7 days")


def _normal_scope_without_period(video: ChannelVideo) -> tuple[str, str, str] | None:
    topic = _recognized(video.topic, RECOGNIZED_TOPICS)
    format_name = _recognized(video.format, RECOGNIZED_FORMATS)
    bucket = length_bucket(video.length_seconds)
    if topic is None or format_name is None or bucket == "unknown":
        return None
    return topic, format_name.casefold(), bucket


def _text(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().casefold()
    if normalized in {"unknown", "n/a", "na", "none", "null", "unavailable", "not available"}:
        return None
    return value.strip()


def _short_duration(video: ChannelVideo) -> str | None:
    if video.length_seconds is None or video.length_seconds < 0 or video.length_seconds >= 60:
        return None
    return "under 30s" if video.length_seconds < 30 else "30-59s"


def _traffic_group(video: ChannelVideo) -> str | None:
    browse = _finite_non_negative(video.browse_share)
    suggested = _finite_non_negative(video.suggested_share)
    if browse is None or suggested is None or browse > 1 or suggested > 1 or browse + suggested > 1:
        return None
    return "browse/suggested-led" if browse + suggested >= .5 else "other-source-led"


def _follow_up(video: ChannelVideo) -> str | None:
    if video.is_follow_up is True:
        return "follow-up"
    if video.is_follow_up is False:
        return "standalone"
    return None


_SPECS = (
    _PatternSpec("thumbnail_wording", "ctr", "CTR", "thumbnail wording", lambda video: _text(video.thumbnail_wording), lambda video: _finite_ratio(video.ctr), _normal_scope),
    _PatternSpec("hook_type", "average_percentage_viewed", "average percentage viewed", "hook types", lambda video: _text(video.hook_type), lambda video: _finite_ratio(video.average_percentage_viewed), _normal_scope),
    _PatternSpec("topic_performance", "views", "views", "topics", lambda video: _recognized(video.topic, RECOGNIZED_TOPICS), lambda video: video.views, _topic_scope),
    _PatternSpec("short_duration", "average_percentage_viewed", "average percentage viewed", "Short durations", _short_duration, lambda video: _finite_ratio(video.average_percentage_viewed), _short_scope),
    _PatternSpec("subscriber_conversion", "subscriber_conversion_rate", "subscriber conversion", "formats", lambda video: _recognized(video.format, RECOGNIZED_FORMATS), lambda video: _finite_ratio(video.subscriber_conversion_rate), _subscriber_scope),
    _PatternSpec("browse_suggested_response", "views_7d", "7-day views", "traffic-source groups", _traffic_group, lambda video: video.views_7d, _fixed_7d_scope),
    _PatternSpec("geography", "views", "views", "geographies", lambda video: _text(video.geography), lambda video: video.views, _normal_scope),
    _PatternSpec("follow_up_performance", "views_7d", "7-day views", "follow-up types", _follow_up, lambda video: video.views_7d, _long_form_7d_scope),
)
