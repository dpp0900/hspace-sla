from __future__ import annotations

from .models import MetricLimit, SlaThresholds, SlaVerdict


def evaluate_sla(
    *,
    scenario_success: bool,
    duration_ms: int,
    assertion_count: int,
    assertion_failures: int,
    metric_violations: int,
    metrics: dict[str, float] | None,
    thresholds: SlaThresholds,
) -> SlaVerdict:
    reasons: list[str] = []
    metrics = metrics or {}

    if not scenario_success:
        reasons.append("scenario execution failed")

    if thresholds.max_duration_ms is not None and duration_ms > thresholds.max_duration_ms:
        reasons.append(
            f"duration_ms {duration_ms} exceeded max_duration_ms {thresholds.max_duration_ms}"
        )

    if assertion_failures > thresholds.max_assertion_failures:
        reasons.append(
            "assertion_failures "
            f"{assertion_failures} exceeded max_assertion_failures {thresholds.max_assertion_failures}"
        )

    if assertion_count < thresholds.required_assertions:
        reasons.append(
            f"assertion_count {assertion_count} below required_assertions "
            f"{thresholds.required_assertions}"
        )

    metric_limit_violations = metric_limit_reasons(metrics, thresholds.metrics)
    metric_violation_total = metric_violations + len(metric_limit_violations)
    reasons.extend(metric_limit_violations)

    if metric_violation_total > thresholds.max_metric_violations:
        reasons.append(
            "metric_violations "
            f"{metric_violation_total} exceeded max_metric_violations "
            f"{thresholds.max_metric_violations}"
        )

    return SlaVerdict(status="FAIL" if reasons else "PASS", reasons=reasons)


def metric_limit_reasons(
    metrics: dict[str, float],
    limits: dict[str, MetricLimit],
) -> list[str]:
    reasons: list[str] = []
    for name, limit in limits.items():
        if name not in metrics:
            reasons.append(f"metric {name} was not collected")
            continue
        value = metrics[name]
        if limit.max is not None and value > limit.max:
            reasons.append(f"metric {name} value {value} exceeded max {limit.max}")
        if limit.min is not None and value < limit.min:
            reasons.append(f"metric {name} value {value} below min {limit.min}")
    return reasons
