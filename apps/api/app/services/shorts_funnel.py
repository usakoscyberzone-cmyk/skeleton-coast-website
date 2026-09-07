"""Channel-baseline comparisons for advisory Short-to-long-form plans."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal


Classification = Literal["discovery", "conversion", "winner"]


@dataclass(frozen=True)
class ShortMetrics:
    view_rate: float
    avg_percentage_viewed: float
    shares_per_view: float
    subscriber_conversion: float


@dataclass(frozen=True)
class ShortBaseline:
    view_rate: float
    avg_percentage_viewed: float
    shares_per_view: float
    subscriber_conversion: float


def classify_short(metrics: ShortMetrics, baseline: ShortBaseline) -> Classification:
    """Classify only against usable channel rates; no raw view count is considered."""
    values = (*metrics.__dict__.values(), *baseline.__dict__.values())
    if not all(isinstance(value, (int, float)) and isfinite(value) and 0 <= value <= 1 for value in values):
        return "discovery"
    if any(value <= 0 for value in baseline.__dict__.values()):
        return "discovery"
    reach_and_engagement = metrics.view_rate > baseline.view_rate and metrics.avg_percentage_viewed > baseline.avg_percentage_viewed and metrics.shares_per_view > baseline.shares_per_view
    conversion = metrics.subscriber_conversion > baseline.subscriber_conversion
    if reach_and_engagement and conversion:
        return "winner"
    if conversion:
        return "conversion"
    return "discovery"
