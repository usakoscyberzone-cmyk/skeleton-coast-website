"""Conservative, advisory-only packaging recommendations."""

from dataclasses import dataclass
from typing import Literal


MIN_IMPRESSIONS_FOR_PACKAGING_CHANGE = 1000
MIN_AGE_HOURS_FOR_PACKAGING_CHANGE = 12
MATERIAL_DISTRIBUTION_RISE = 0.05
EXTERNAL_SPIKE_DOMINANCE = 0.50


@dataclass(frozen=True)
class VideoDecisionContext:
    age_hours: float | None
    impressions: int | None
    ctr: float | None
    avg_percentage_viewed: float | None
    browse_trend: float | None = None
    suggested_trend: float | None = None
    realtime_trend: float | None = None
    external_share: float | None = None
    comparable_sample_size: int = 0
    comparable_ctr: float | None = None
    comparable_retention: float | None = None


@dataclass(frozen=True)
class RecommendationDecision:
    state: Literal["green", "amber", "red"]
    action: str
    reason: str
    confidence: Literal["low", "medium", "high"]
    data_used: dict[str, float | int | str | None]


def evaluate_video(context: VideoDecisionContext) -> RecommendationDecision:
    data = {
        "age_hours": context.age_hours, "impressions": context.impressions,
        "ctr": context.ctr, "avg_percentage_viewed": context.avg_percentage_viewed,
        "browse_trend": context.browse_trend, "suggested_trend": context.suggested_trend,
        "realtime_trend": context.realtime_trend, "external_share": context.external_share,
        "comparable_sample_size": context.comparable_sample_size,
        "comparable_ctr": context.comparable_ctr, "comparable_retention": context.comparable_retention,
    }
    if context.external_share is not None and context.external_share >= EXTERNAL_SPIKE_DOMINANCE:
        return _amber("Wait and inspect the source mix before changing packaging.", "External traffic dominates this sample.", "low", data)
    if context.age_hours is None or context.impressions is None:
        return _amber("Wait for complete analytics before changing packaging.", "Video age or impression evidence is unavailable.", "low", data)
    if context.age_hours < MIN_AGE_HOURS_FOR_PACKAGING_CHANGE or context.impressions < MIN_IMPRESSIONS_FOR_PACKAGING_CHANGE:
        return _amber("Wait for a larger, older sample before changing packaging.", "The video has not reached the conservative age and impression thresholds.", "low", data)
    distribution_rising = any(value is not None and value >= MATERIAL_DISTRIBUTION_RISE for value in (context.browse_trend, context.suggested_trend))
    if distribution_rising and context.realtime_trend is not None and context.realtime_trend >= 0:
        return RecommendationDecision("green", "Leave packaging unchanged.", "Browse or Suggested distribution is materially rising and realtime is non-declining.", "high", data)
    required = (context.ctr, context.avg_percentage_viewed, context.comparable_ctr, context.comparable_retention)
    if context.comparable_sample_size < 5 or any(value is None for value in required):
        return _amber("Wait and inspect more comparable channel evidence.", "Comparable evidence is unavailable or below five matching videos.", "low", data)
    distribution_stalled = all(value is not None and value <= 0 for value in (context.browse_trend, context.suggested_trend, context.realtime_trend))
    underperforming = sum((context.ctr < context.comparable_ctr, context.avg_percentage_viewed < context.comparable_retention))
    if distribution_stalled and underperforming >= 2:
        return RecommendationDecision("red", "Test one packaging change.", "Distribution is stalled or declining and both CTR and retention underperform comparable channel videos.", "medium", data)
    return _amber("Wait and inspect the next analytics snapshot.", "The evidence is mixed and does not support a packaging change yet.", "medium", data)


def _amber(action: str, reason: str, confidence: Literal["low", "medium"], data: dict[str, float | int | str | None]) -> RecommendationDecision:
    return RecommendationDecision("amber", action, reason, confidence, data)
