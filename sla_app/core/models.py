from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALLOWED_ACTIONS = {
    "launch_app",
    "tap",
    "input",
    "wait",
    "assert_text",
    "assert_exists",
    "screenshot",
    "collect_metrics",
    "metric_check",
}

ASSERTION_ACTIONS = {"assert_text", "assert_exists"}


@dataclass(frozen=True)
class MetricLimit:
    min: float | None = None
    max: float | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "MetricLimit":
        return cls(
            min=_optional_float(data.get("min")),
            max=_optional_float(data.get("max")),
        )

    def to_dict(self) -> dict[str, float]:
        result: dict[str, float] = {}
        if self.min is not None:
            result["min"] = self.min
        if self.max is not None:
            result["max"] = self.max
        return result


@dataclass(frozen=True)
class SlaThresholds:
    max_duration_ms: int | None = None
    max_assertion_failures: int = 0
    max_metric_violations: int = 0
    required_assertions: int = 0
    metrics: dict[str, MetricLimit] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "SlaThresholds":
        data = data or {}
        metric_limits = {}
        raw_metrics = data.get("metrics") or {}
        if isinstance(raw_metrics, dict):
            for name, limit in raw_metrics.items():
                if isinstance(limit, dict):
                    metric_limits[str(name)] = MetricLimit.from_mapping(limit)
        return cls(
            max_duration_ms=_optional_int(data.get("max_duration_ms")),
            max_assertion_failures=int(data.get("max_assertion_failures", 0)),
            max_metric_violations=int(data.get("max_metric_violations", 0)),
            required_assertions=int(data.get("required_assertions", 0)),
            metrics=metric_limits,
        )

    def merged_with(self, override: "SlaThresholds | None") -> "SlaThresholds":
        if override is None:
            return self
        metrics = {**self.metrics, **override.metrics}
        return SlaThresholds(
            max_duration_ms=override.max_duration_ms
            if override.max_duration_ms is not None
            else self.max_duration_ms,
            max_assertion_failures=override.max_assertion_failures,
            max_metric_violations=override.max_metric_violations,
            required_assertions=override.required_assertions or self.required_assertions,
            metrics=metrics,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "max_assertion_failures": self.max_assertion_failures,
            "max_metric_violations": self.max_metric_violations,
        }
        if self.max_duration_ms is not None:
            data["max_duration_ms"] = self.max_duration_ms
        if self.required_assertions:
            data["required_assertions"] = self.required_assertions
        if self.metrics:
            data["metrics"] = {name: limit.to_dict() for name, limit in self.metrics.items()}
        return data


@dataclass(frozen=True)
class AppTarget:
    platform: str = "android"
    apk: str | None = None
    app_package: str | None = None
    app_activity: str | None = None
    app_wait_activity: str | None = None
    no_reset: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AppTarget":
        return cls(
            platform=str(data.get("platform", "android")),
            apk=_optional_str(data.get("apk")),
            app_package=_optional_str(data.get("app_package")),
            app_activity=_optional_str(data.get("app_activity")),
            app_wait_activity=_optional_str(data.get("app_wait_activity")),
            no_reset=bool(data.get("no_reset", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"platform": self.platform}
        for key in ("apk", "app_package", "app_activity", "app_wait_activity"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.no_reset:
            data["no_reset"] = True
        return data


@dataclass(frozen=True)
class ActionStep:
    action: str
    selector: str | None = None
    text: str | None = None
    value: str | int | float | bool | None = None
    timeout_ms: int | None = None
    name: str | None = None
    metric: str | None = None
    min: float | None = None
    max: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ActionStep":
        return cls(
            action=str(data.get("action", "")),
            selector=_optional_str(data.get("selector")),
            text=_optional_str(data.get("text")),
            value=data.get("value"),
            timeout_ms=_optional_int(data.get("timeout_ms")),
            name=_optional_str(data.get("name")),
            metric=_optional_str(data.get("metric")),
            min=_optional_float(data.get("min")),
            max=_optional_float(data.get("max")),
            raw=dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"action": self.action}
        for key in ("selector", "text", "value", "timeout_ms", "name", "metric", "min", "max"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        for key, value in self.raw.items():
            data.setdefault(key, value)
        return data


@dataclass(frozen=True)
class Scenario:
    name: str
    steps: list[ActionStep]
    thresholds: SlaThresholds | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.thresholds:
            data["thresholds"] = self.thresholds.to_dict()
        return data


@dataclass(frozen=True)
class TestSuite:
    name: str
    app: AppTarget
    scenarios: list[Scenario]
    thresholds: SlaThresholds = field(default_factory=SlaThresholds)
    suite_id: str | None = None
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "app": self.app.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }


@dataclass(frozen=True)
class StepResult:
    index: int
    action: str
    success: bool
    duration_ms: int
    message: str = ""
    screenshot_path: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    assertion_failure: bool = False
    metric_violation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "screenshot_path": self.screenshot_path,
            "metrics": self.metrics,
            "assertion_failure": self.assertion_failure,
            "metric_violation": self.metric_violation,
        }


@dataclass(frozen=True)
class SlaVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reasons": self.reasons}


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    success: bool
    duration_ms: int
    step_results: list[StepResult]
    assertion_count: int
    assertion_failures: int
    metric_violations: int
    metrics: dict[str, float]
    verdict: SlaVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "step_results": [step.to_dict() for step in self.step_results],
            "assertion_count": self.assertion_count,
            "assertion_failures": self.assertion_failures,
            "metric_violations": self.metric_violations,
            "metrics": self.metrics,
            "verdict": self.verdict.to_dict(),
        }


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    suite_id: str
    suite_name: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    assertion_failures: int
    metric_violations: int
    reasons: list[str]
    artifact_dir: str
    scenarios: list[ScenarioResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "assertion_failures": self.assertion_failures,
            "metric_violations": self.metric_violations,
            "reasons": self.reasons,
            "artifact_dir": self.artifact_dir,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
