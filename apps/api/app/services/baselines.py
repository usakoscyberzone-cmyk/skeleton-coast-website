"""Channel-only comparison baselines for guarded recommendations."""

from dataclasses import dataclass
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


def length_bucket(length_seconds: int | None) -> str:
    if length_seconds is None or length_seconds < 60:
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
    matching = [
        video for video in videos
        if (video.topic or "").casefold() == topic.casefold()
        and (video.format or "").casefold() == format.casefold()
        and length_bucket(video.length_seconds) == length_bucket_name
    ]
    if len(matching) < 5:
        return Baseline(sample_size=len(matching), ctr=None, retention=None, confidence="low")
    ctrs = [video.ctr for video in matching if video.ctr is not None]
    retentions = [video.average_percentage_viewed for video in matching if video.average_percentage_viewed is not None]
    return Baseline(
        sample_size=len(matching),
        ctr=median(ctrs) if ctrs else None,
        retention=median(retentions) if retentions else None,
        confidence="high",
    )
