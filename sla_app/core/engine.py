from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .evaluator import evaluate_sla
from .models import (
    ASSERTION_ACTIONS,
    ActionStep,
    RunRecord,
    Scenario,
    ScenarioResult,
    StepResult,
    TestSuite,
)


class ExecutionAdapter(Protocol):
    def launch_app(self) -> None: ...

    def tap(self, step: ActionStep) -> None: ...

    def input(self, step: ActionStep) -> None: ...

    def wait(self, step: ActionStep) -> None: ...

    def assert_text(self, step: ActionStep) -> None: ...

    def assert_exists(self, step: ActionStep) -> None: ...

    def screenshot(self, step: ActionStep, artifact_dir: Path) -> str: ...

    def collect_metrics(self, step: ActionStep) -> dict[str, float]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ExecutionOptions:
    run_id: str | None = None
    artifact_dir: Path | None = None


def execute_suite(
    suite: TestSuite,
    adapter: ExecutionAdapter,
    *,
    suite_id: str,
    options: ExecutionOptions | None = None,
) -> RunRecord:
    options = options or ExecutionOptions()
    run_id = options.run_id or uuid.uuid4().hex
    artifact_dir = Path(options.artifact_dir) if options.artifact_dir else Path("artifacts") / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    run_start = time.monotonic()
    scenario_results: list[ScenarioResult] = []
    reasons: list[str] = []

    try:
        for scenario in suite.scenarios:
            result = _execute_scenario(
                scenario,
                suite_thresholds=suite.thresholds,
                adapter=adapter,
                artifact_dir=artifact_dir,
            )
            scenario_results.append(result)
            reasons.extend(f"{result.name}: {reason}" for reason in result.verdict.reasons)
    finally:
        adapter.close()

    duration_ms = _elapsed_ms(run_start)
    ended_at = _utc_now()
    assertion_failures = sum(result.assertion_failures for result in scenario_results)
    metric_violations = sum(result.metric_violations for result in scenario_results)
    status = "PASS" if scenario_results and all(result.verdict.passed for result in scenario_results) else "FAIL"

    return RunRecord(
        run_id=run_id,
        suite_id=suite_id,
        suite_name=suite.name,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        assertion_failures=assertion_failures,
        metric_violations=metric_violations,
        reasons=reasons,
        artifact_dir=str(artifact_dir),
        scenarios=scenario_results,
    )


def _execute_scenario(
    scenario: Scenario,
    *,
    suite_thresholds,
    adapter: ExecutionAdapter,
    artifact_dir: Path,
) -> ScenarioResult:
    thresholds = suite_thresholds.merged_with(scenario.thresholds)
    scenario_start = time.monotonic()
    step_results: list[StepResult] = []
    metrics: dict[str, float] = {}
    scenario_success = True

    for index, step in enumerate(scenario.steps, start=1):
        started = time.monotonic()
        success = True
        message = ""
        failure_category = ""
        screenshot_path = None
        step_metrics: dict[str, float] = {}
        assertion_failure = False
        metric_violation = False
        try:
            if step.action == "launch_app":
                adapter.launch_app()
            elif step.action == "tap":
                adapter.tap(step)
            elif step.action == "input":
                adapter.input(step)
            elif step.action == "wait":
                adapter.wait(step)
            elif step.action == "assert_text":
                adapter.assert_text(step)
            elif step.action == "assert_exists":
                adapter.assert_exists(step)
            elif step.action == "screenshot":
                screenshot_path = adapter.screenshot(step, artifact_dir)
            elif step.action == "collect_metrics":
                step_metrics = adapter.collect_metrics(step)
                metrics.update(step_metrics)
            elif step.action == "metric_check":
                metric_violation = _metric_check_failed(step, metrics)
                if metric_violation:
                    success = False
                    message = f"metric {step.metric} violated configured bounds"
            else:
                success = False
                message = f"unsupported action {step.action}"
        except AssertionError as exc:
            success = False
            assertion_failure = step.action in ASSERTION_ACTIONS
            message = str(exc)
        except SystemExit as exc:
            success = False
            message = _system_exit_message(exc)
        except Exception as exc:  # noqa: BLE001 - execution errors must be recorded in the run.
            success = False
            message = str(exc)

        if not success:
            scenario_success = False
            assertion_failure = assertion_failure or step.action in ASSERTION_ACTIONS
            failure_category = _failure_category(
                step,
                message=message,
                assertion_failure=assertion_failure,
                metric_violation=metric_violation,
            )

        step_results.append(
            StepResult(
                index=index,
                action=step.action,
                success=success,
                duration_ms=_elapsed_ms(started),
                message=message,
                failure_category=failure_category,
                screenshot_path=screenshot_path,
                metrics=step_metrics,
                assertion_failure=assertion_failure,
                metric_violation=metric_violation,
            )
        )

        if not success and step.action not in ASSERTION_ACTIONS and step.action != "metric_check":
            break

    duration_ms = _elapsed_ms(scenario_start)
    assertion_count = sum(
        1 for result in step_results if result.action in ASSERTION_ACTIONS and result.success
    )
    assertion_failures = sum(1 for result in step_results if result.assertion_failure)
    metric_violations = sum(1 for result in step_results if result.metric_violation)
    verdict = evaluate_sla(
        scenario_success=scenario_success,
        duration_ms=duration_ms,
        assertion_count=assertion_count,
        assertion_failures=assertion_failures,
        metric_violations=metric_violations,
        metrics=metrics,
        thresholds=thresholds,
    )
    return ScenarioResult(
        name=scenario.name,
        success=scenario_success,
        duration_ms=duration_ms,
        step_results=step_results,
        assertion_count=assertion_count,
        assertion_failures=assertion_failures,
        metric_violations=metric_violations,
        metrics=metrics,
        verdict=verdict,
    )


def _metric_check_failed(step: ActionStep, metrics: dict[str, float]) -> bool:
    if not step.metric or step.metric not in metrics:
        return True
    value = metrics[step.metric]
    if step.max is not None and value > step.max:
        return True
    if step.min is not None and value < step.min:
        return True
    return False


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _system_exit_message(exc: SystemExit) -> str:
    if isinstance(exc.code, int):
        return f"launcher exited with code {exc.code}"
    if exc.code:
        return str(exc.code)
    return "launcher exited"


def _failure_category(
    step: ActionStep,
    *,
    message: str,
    assertion_failure: bool,
    metric_violation: bool,
) -> str:
    normalized = message.lower()
    if step.action == "launch_app" or "launcher exited" in normalized or "appium" in normalized:
        return "환경/실행"
    if metric_violation or step.action == "metric_check":
        return "지표 위반"
    if assertion_failure:
        if "element not found" in normalized or step.action == "assert_exists":
            return "요소 찾기 실패"
        if "text not found" in normalized or step.action == "assert_text":
            return "텍스트 검증 실패"
        return "검증 실패"
    if "element not found" in normalized:
        return "요소 찾기 실패"
    if "unsupported action" in normalized:
        return "지원하지 않는 동작"
    return "실행 오류"
