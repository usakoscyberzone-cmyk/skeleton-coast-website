from app.services.recommendation_engine import VideoDecisionContext, evaluate_video


def context(**changes):
    values = dict(
        age_hours=18, impressions=5_000, ctr=0.04,
        avg_percentage_viewed=0.30, browse_trend=-0.08, suggested_trend=-0.03,
        realtime_trend=-0.05, external_share=0.10, comparable_sample_size=8,
        comparable_ctr=0.07, comparable_retention=0.50,
    )
    values.update(changes)
    return VideoDecisionContext(**values)


def test_small_sample_returns_amber_wait_not_red():
    result = evaluate_video(context(age_hours=2, impressions=120, comparable_sample_size=8))
    assert result.state == "amber"
    assert "wait" in result.action.lower()


def test_rising_browse_with_healthy_realtime_returns_green():
    result = evaluate_video(context(browse_trend=0.20, realtime_trend=0.0))
    assert result.state == "green"
    assert "leave" in result.action.lower()


def test_threshold_boundaries_allow_red_only_at_age_and_impression_minimums():
    assert evaluate_video(context(age_hours=11.99)).state == "amber"
    assert evaluate_video(context(impressions=999)).state == "amber"
    assert evaluate_video(context(age_hours=12, impressions=1000)).state == "red"


def test_missing_metrics_are_amber_and_data_used_does_not_invent_values():
    result = evaluate_video(context(ctr=None, avg_percentage_viewed=None))
    assert result.state == "amber"
    assert result.data_used["ctr"] is None
    assert result.data_used["avg_percentage_viewed"] is None


def test_external_spike_dominance_is_amber_even_with_poor_comparables():
    result = evaluate_video(context(external_share=0.60))
    assert result.state == "amber"
    assert "external" in result.reason.lower()


def test_one_underperforming_comparable_signal_cannot_make_red():
    result = evaluate_video(context(avg_percentage_viewed=0.60))
    assert result.state == "amber"


def test_fewer_than_five_comparables_is_non_comparative_amber():
    result = evaluate_video(context(comparable_sample_size=4))
    assert result.state == "amber"
    assert result.confidence == "low"


def test_every_decision_has_explainable_fields():
    result = evaluate_video(context())
    assert result.action and result.reason and result.confidence
    assert {"age_hours", "impressions", "ctr", "avg_percentage_viewed"} <= result.data_used.keys()
