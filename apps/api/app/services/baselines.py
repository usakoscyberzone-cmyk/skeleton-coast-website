"""Channel-only comparison baselines for guarded recommendations."""

from dataclasses import dataclass
import math
from statistics import median
from typing import Iterable, Literal, Protocol


class ComparableVideo(Protocol):
    topic: str | None
    format: str | None
    length_seconds: int | None
    ctr: float | None
    average_percentage_viewed: float | None


@dataclass(frozen=True)
class Baseline:
    sample_size: int
    ctr: float | None
    retention: float | None
    confidence: Literal["low", "high"]


RECOGNIZED_FORMATS = {"long", "short", "live"}
RECOGNIZED_TOPICS = {"fishing", "namibia travel", "angola", "history", "4x4", "current events"}


def length_bucket(length_seconds: int | None) -> str:
    if (
        length_seconds is None
        or isinstance(length_seconds, bool)
        or not isinstance(length_seconds, (int, float))
        or not math.isfinite(length_seconds)
        or length_seconds < 0
    ):
        return "unknown"
    if length_seconds < 60:
        return "<1m"
    if length_seconds <= 300:
        return "1-5m"
    if length_seconds <= 900:
        return "5-15m"
    return "15m+"


def build_channel_baseline(
    topic: str, format: str, length_bucket_name: str, videos: Iterable[ComparableVideo]
) -> Baseline:
    """Use actual matching videos; grouping labels alone never form a baseline."""
    if not _valid_metadata(topic, format, length_bucket_name):
        return Baseline(sample_size=0, ctr=None, retention=None, confidence="low")
    matching = [
        video for video in videos
        if _valid_metadata(video.topic, video.format, length_bucket(video.length_seconds))
        and video.topic.casefold() == topic.casefold()
        and video.format.casefold() == format.casefold()
        and length_bucket(video.length_seconds) == length_bucket_name
    ]
    if len(matching) < 5:
        return Baseline(sample_size=len(matching), ctr=None, retention=None, confidence="low")
    ctrs = [video.ctr for video in matching if _valid_ratio(video.ctr)]
    retentions = [video.average_percentage_viewed for video in matching if _valid_ratio(video.average_percentage_viewed)]
    return Baseline(
        sample_size=len(matching),
        ctr=median(ctrs) if ctrs else None,
        retention=median(retentions) if retentions else None,
        confidence="high",
    )


def _valid_metadata(topic: str | None, format: str | None, bucket: str) -> bool:
    return (
        isinstance(topic, str) and topic.casefold() in RECOGNIZED_TOPICS
        and isinstance(format, str) and format.casefold() in RECOGNIZED_FORMATS
        and bucket in {"<1m", "1-5m", "5-15m", "15m+"}
    )


def _valid_ratio(value: float | None) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )
