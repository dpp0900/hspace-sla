from __future__ import annotations

import tempfile
import unittest

from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.models import ActionStep, AppTarget, Scenario, SlaThresholds
from sla_app.core.models import TestSuite as SlaTestSuite


class SystemExitAdapter:
    def launch_app(self) -> None:
        raise SystemExit(1)

    def activate_app(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def terminate_app(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def background_app(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def tap(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def input(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def back(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def swipe(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def scroll(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def scroll_to_text(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def wait(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_text(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_not_text(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_exists(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_not_exists(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_visible(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_enabled(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_attribute(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_current_package(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def assert_current_activity(self, step: ActionStep) -> None:
        raise AssertionError("not used")

    def screenshot(self, step: ActionStep, artifact_dir):
        raise AssertionError("not used")

    def collect_metrics(self, step: ActionStep) -> dict[str, float]:
        raise AssertionError("not used")

    def close(self) -> None:
        pass


class RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def launch_app(self) -> None:
        self.calls.append("launch_app")

    def activate_app(self, step: ActionStep) -> None:
        self.calls.append(f"activate_app:{step.package}")

    def terminate_app(self, step: ActionStep) -> None:
        self.calls.append(f"terminate_app:{step.package}")

    def background_app(self, step: ActionStep) -> None:
        self.calls.append(f"background_app:{step.timeout_ms}")

    def tap(self, step: ActionStep) -> None:
        self.calls.append("tap")

    def input(self, step: ActionStep) -> None:
        self.calls.append("input")

    def back(self, step: ActionStep) -> None:
        self.calls.append("back")

    def swipe(self, step: ActionStep) -> None:
        self.calls.append(f"swipe:{step.direction}")

    def scroll(self, step: ActionStep) -> None:
        self.calls.append(f"scroll:{step.direction}")

    def scroll_to_text(self, step: ActionStep) -> None:
        self.calls.append(f"scroll_to_text:{step.text}")

    def wait(self, step: ActionStep) -> None:
        self.calls.append("wait")

    def assert_text(self, step: ActionStep) -> None:
        self.calls.append("assert_text")

    def assert_not_text(self, step: ActionStep) -> None:
        self.calls.append(f"assert_not_text:{step.text}")

    def assert_exists(self, step: ActionStep) -> None:
        self.calls.append("assert_exists")

    def assert_not_exists(self, step: ActionStep) -> None:
        self.calls.append("assert_not_exists")

    def assert_visible(self, step: ActionStep) -> None:
        self.calls.append("assert_visible")

    def assert_enabled(self, step: ActionStep) -> None:
        self.calls.append("assert_enabled")

    def assert_attribute(self, step: ActionStep) -> None:
        self.calls.append(f"assert_attribute:{step.attribute}")

    def assert_current_package(self, step: ActionStep) -> None:
        self.calls.append(f"assert_current_package:{step.package}")

    def assert_current_activity(self, step: ActionStep) -> None:
        self.calls.append(f"assert_current_activity:{step.activity}")

    def screenshot(self, step: ActionStep, artifact_dir):
        self.calls.append("screenshot")
        return str(artifact_dir / "screen.png")

    def collect_metrics(self, step: ActionStep) -> dict[str, float]:
        self.calls.append("collect_metrics")
        return {"memory_mb": 42}

    def close(self) -> None:
        self.calls.append("close")


class EngineTests(unittest.TestCase):
    def test_launcher_system_exit_becomes_failed_run(self) -> None:
        suite = SlaTestSuite(
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

    def test_dispatches_extended_appium_sla_actions(self) -> None:
        suite = SlaTestSuite(
            name="Extended Actions",
            app=AppTarget(platform="android", apk="app.apk"),
            thresholds=SlaThresholds(max_assertion_failures=0, max_metric_violations=0),
            scenarios=[
                Scenario(
                    name="gestures and state",
                    steps=[
                        ActionStep(action="launch_app"),
                        ActionStep(action="terminate_app", package="com.example"),
                        ActionStep(action="activate_app", package="com.example"),
                        ActionStep(action="background_app", timeout_ms=1500),
                        ActionStep(action="swipe", direction="up", percent=0.75),
                        ActionStep(action="scroll", direction="down", percent=1.0),
                        ActionStep(action="scroll_to_text", text="Terms"),
                        ActionStep(action="back"),
                        ActionStep(action="assert_not_text", text="Crash"),
                        ActionStep(action="assert_visible", selector="id=login"),
                        ActionStep(action="assert_not_exists", selector="id=error"),
                        ActionStep(action="assert_enabled", selector="id=login"),
                        ActionStep(
                            action="assert_attribute",
                            selector="id=login",
                            attribute="enabled",
                            value="true",
                        ),
                        ActionStep(action="assert_current_package", package="com.example"),
                        ActionStep(action="assert_current_activity", activity="*.MainActivity"),
                        ActionStep(action="collect_metrics"),
                        ActionStep(action="metric_check", metric="memory_mb", max=128),
                    ],
                )
            ],
        )
        adapter = RecordingAdapter()

        with tempfile.TemporaryDirectory() as tmp:
            run = execute_suite(
                suite,
                adapter,
                suite_id="extended-actions",
                options=ExecutionOptions(run_id="run-extended", artifact_dir=tmp),
            )

        self.assertEqual(run.status, "PASS")
        self.assertEqual(
            adapter.calls,
            [
                "launch_app",
                "terminate_app:com.example",
                "activate_app:com.example",
                "background_app:1500",
                "swipe:up",
                "scroll:down",
                "scroll_to_text:Terms",
                "back",
                "assert_not_text:Crash",
                "assert_visible",
                "assert_not_exists",
                "assert_enabled",
                "assert_attribute:enabled",
                "assert_current_package:com.example",
                "assert_current_activity:*.MainActivity",
                "collect_metrics",
                "close",
            ],
        )
        self.assertEqual(run.scenarios[0].metrics["memory_mb"], 42)


if __name__ == "__main__":
    unittest.main()
