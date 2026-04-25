from __future__ import annotations

import unittest

from sla_app.core.evaluator import evaluate_sla
from sla_app.core.models import MetricLimit, SlaThresholds


class EvaluatorTests(unittest.TestCase):
    def test_passes_when_thresholds_are_met(self) -> None:
        verdict = evaluate_sla(
            scenario_success=True,
            duration_ms=120,
            assertion_count=1,
            assertion_failures=0,
            metric_violations=0,
            metrics={"memory_mb": 80},
            thresholds=SlaThresholds(
                max_duration_ms=500,
                required_assertions=1,
                metrics={"memory_mb": MetricLimit(max=128)},
            ),
        )

        self.assertEqual(verdict.status, "PASS")

    def test_fails_when_duration_exceeds_threshold(self) -> None:
        verdict = evaluate_sla(
            scenario_success=True,
            duration_ms=900,
            assertion_count=1,
            assertion_failures=0,
            metric_violations=0,
            metrics={},
            thresholds=SlaThresholds(max_duration_ms=500),
        )

        self.assertEqual(verdict.status, "FAIL")
        self.assertIn("duration_ms 900 exceeded max_duration_ms 500", verdict.reasons)

    def test_fails_when_assertion_fails(self) -> None:
        verdict = evaluate_sla(
            scenario_success=True,
            duration_ms=100,
            assertion_count=0,
            assertion_failures=1,
            metric_violations=0,
            metrics={},
            thresholds=SlaThresholds(max_assertion_failures=0),
        )

        self.assertEqual(verdict.status, "FAIL")
        self.assertTrue(any("assertion_failures" in reason for reason in verdict.reasons))

    def test_fails_when_metric_limit_is_violated(self) -> None:
        verdict = evaluate_sla(
            scenario_success=True,
            duration_ms=100,
            assertion_count=1,
            assertion_failures=0,
            metric_violations=0,
            metrics={"memory_mb": 256},
            thresholds=SlaThresholds(
                max_metric_violations=0,
                metrics={"memory_mb": MetricLimit(max=128)},
            ),
        )

        self.assertEqual(verdict.status, "FAIL")
        self.assertTrue(any("memory_mb" in reason for reason in verdict.reasons))


if __name__ == "__main__":
    unittest.main()
