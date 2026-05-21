from __future__ import annotations

import tempfile
import unittest

from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.models import ActionStep, AppTarget, Scenario, SlaThresholds, TestSuite


class SystemExitAdapter:
    def launch_app(self) -> None:
        raise SystemExit(1)

    def tap(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def input(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def wait(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_text(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_exists(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def screenshot(self, step: ActionStep, artifact_dir):
        raise AssertionError("not used")

    def collect_metrics(self, step: ActionStep) -> dict[str, float]:
        raise AssertionError("not used")

    def close(self) -> None:
        pass


class EngineTests(unittest.TestCase):
    def test_launcher_system_exit_becomes_failed_run(self) -> None:
        suite = TestSuite(
            name="Run Failure",
            app=AppTarget(platform="android", apk="app.apk"),
            thresholds=SlaThresholds(max_assertion_failures=0, max_metric_violations=0),
            scenarios=[
                Scenario(
                    name="launch",
                    steps=[ActionStep(action="launch_app"), ActionStep(action="wait")],
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            run = execute_suite(
                suite,
                SystemExitAdapter(),
                suite_id="run-failure",
                options=ExecutionOptions(run_id="run-1", artifact_dir=tmp),
            )

        self.assertEqual(run.status, "FAIL")
        self.assertEqual(run.scenarios[0].step_results[0].message, "launcher exited with code 1")
        self.assertEqual(run.scenarios[0].step_results[0].failure_category, "환경/실행")
        self.assertEqual(len(run.scenarios[0].step_results), 1)


if __name__ == "__main__":
    unittest.main()
