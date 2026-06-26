from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .models import ALLOWED_ACTIONS, ActionStep, AppTarget, Scenario, SlaThresholds, TestSuite


class SuiteValidationError(ValueError):
    pass


def load_suite(path: str | Path) -> TestSuite:
    suite_path = Path(path)
    return suite_from_yaml_text(suite_path.read_text(encoding="utf-8"), source_path=suite_path)


def suite_from_yaml_text(text: str, *, source_path: str | Path | None = None) -> TestSuite:
    data = _yaml_load(text)
    if not isinstance(data, dict):
        raise SuiteValidationError("suite YAML must be a mapping")

    suite = _suite_from_mapping(data, source_path=Path(source_path) if source_path else None)
    validate_suite(suite)
    return suite


def suite_to_yaml(suite: TestSuite) -> str:
    return _yaml_dump(suite.to_dict())


def validate_suite(suite: TestSuite) -> None:
    if not suite.name:
        raise SuiteValidationError("suite name is required")
    if suite.app.platform != "android":
        raise SuiteValidationError("only android platform is supported in this MVP")
    if not suite.app.apk and not (suite.app.app_package and suite.app.app_activity):
        raise SuiteValidationError("android app target requires apk or app_package/app_activity")
    if not suite.scenarios:
        raise SuiteValidationError("at least one scenario is required")

    for scenario in suite.scenarios:
        if not scenario.name:
            raise SuiteValidationError("scenario name is required")
        if not scenario.steps:
            raise SuiteValidationError(f"scenario {scenario.name} requires at least one step")
        for step in scenario.steps:
            _validate_step(step, scenario.name)


def _suite_from_mapping(data: dict[str, Any], *, source_path: Path | None) -> TestSuite:
    raw_app = data.get("app")
    if not isinstance(raw_app, dict):
        raise SuiteValidationError("app mapping is required")

    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, list):
        raise SuiteValidationError("scenarios list is required")

    scenarios: list[Scenario] = []
    for index, raw_scenario in enumerate(raw_scenarios, start=1):
        if not isinstance(raw_scenario, dict):
            raise SuiteValidationError(f"scenario #{index} must be a mapping")
        raw_steps = raw_scenario.get("steps")
        if not isinstance(raw_steps, list):
            raise SuiteValidationError(f"scenario #{index} steps must be a list")
        steps = []
        for step_index, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                raise SuiteValidationError(
                    f"scenario #{index} step #{step_index} must be a mapping"
                )
            steps.append(ActionStep.from_mapping(raw_step))
        scenario_thresholds = None
        if isinstance(raw_scenario.get("thresholds"), dict):
            scenario_thresholds = SlaThresholds.from_mapping(raw_scenario["thresholds"])
        scenarios.append(
            Scenario(
                name=str(raw_scenario.get("name", "")).strip(),
                steps=steps,
                thresholds=scenario_thresholds,
            )
        )

    return TestSuite(
        name=str(data.get("name", "")).strip(),
        app=AppTarget.from_mapping(raw_app),
        thresholds=SlaThresholds.from_mapping(data.get("thresholds")),
        scenarios=scenarios,
        source_path=source_path,
    )


def _validate_step(step: ActionStep, scenario_name: str) -> None:
    if step.action not in ALLOWED_ACTIONS:
        raise SuiteValidationError(
            f"scenario {scenario_name} contains unsupported action: {step.action}"
        )

    if step.action == "tap" and not (step.selector or step.text):
        raise SuiteValidationError("tap requires selector or text")
    if step.action == "input" and not (step.selector and step.value is not None):
        raise SuiteValidationError("input requires selector and value")
    if step.action in {"swipe", "scroll"}:
        if step.direction and step.direction.lower() not in {"up", "down", "left", "right"}:
            raise SuiteValidationError(f"{step.action} direction must be up, down, left, or right")
        if step.percent is not None and step.percent <= 0:
            raise SuiteValidationError(f"{step.action} percent must be greater than 0")
        if step.action == "swipe" and step.percent is not None and step.percent > 1:
            raise SuiteValidationError("swipe percent must be less than or equal to 1")
    if step.action == "scroll_to_text" and not step.text:
        raise SuiteValidationError("scroll_to_text requires text")
    if step.action in {"assert_text", "assert_not_text"} and not step.text:
        raise SuiteValidationError(f"{step.action} requires text")
    if step.action in {"assert_exists", "assert_not_exists"} and not (
        step.selector or step.text
    ):
        raise SuiteValidationError(f"{step.action} requires selector or text")
    if step.action in {"assert_visible", "assert_enabled"} and not (step.selector or step.text):
        raise SuiteValidationError(f"{step.action} requires selector or text")
    if step.action == "assert_attribute":
        if not (step.selector or step.text):
            raise SuiteValidationError("assert_attribute requires selector or text")
        if not step.attribute:
            raise SuiteValidationError("assert_attribute requires attribute")
        if step.value is None:
            raise SuiteValidationError("assert_attribute requires value")
    if step.action == "metric_check":
        if not step.metric:
            raise SuiteValidationError("metric_check requires metric")
        if step.min is None and step.max is None:
            raise SuiteValidationError("metric_check requires min or max")
    if step.action == "assert_current_package" and not (step.package or step.value):
        raise SuiteValidationError("assert_current_package requires package")
    if step.action == "assert_current_activity" and not (step.activity or step.value):
        raise SuiteValidationError("assert_current_activity requires activity")


def _yaml_load(text: str) -> Any:
    try:
        import yaml
    except ImportError:
        return _simple_yaml_load(text)
    return yaml.safe_load(text)


def _yaml_dump(data: dict[str, Any]) -> str:
    try:
        import yaml
    except ImportError:
        return _simple_yaml_dump(data)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _simple_yaml_load(text: str) -> Any:
    lines = _preprocess_yaml_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise SuiteValidationError("could not parse complete YAML document")
    return value


def _preprocess_yaml_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line.strip()))
    return lines


def _parse_block(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index
    current_indent, content = lines[index]
    if current_indent != indent:
        raise SuiteValidationError("invalid YAML indentation")
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_dict(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise SuiteValidationError("unexpected nested YAML value")
        if content.startswith("- "):
            break
        key, value = _split_key_value(content)
        index += 1
        if value == "":
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                result[key] = child
            else:
                result[key] = None
        else:
            result[key] = _parse_scalar(value)
    return result, index


def _parse_list(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not content.startswith("- "):
            break
        item_content = content[2:].strip()
        index += 1
        if item_content == "":
            if index < len(lines) and lines[index][0] > indent:
                item, index = _parse_block(lines, index, lines[index][0])
            else:
                item = None
        elif ":" in item_content:
            key, value = _split_key_value(item_content)
            item = {key: _parse_scalar(value) if value else None}
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                if isinstance(child, dict):
                    item.update(child)
                else:
                    raise SuiteValidationError("list item mapping cannot merge non-mapping child")
        else:
            item = _parse_scalar(item_content)
        result.append(item)
    return result, index


def _split_key_value(content: str) -> tuple[str, str]:
    if ":" not in content:
        raise SuiteValidationError(f"expected key/value mapping: {content}")
    key, value = content.split(":", 1)
    key = key.strip()
    if not key:
        raise SuiteValidationError("empty YAML key")
    return key, value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return ast.literal_eval(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _simple_yaml_dump(data: Any, indent: int = 0) -> str:
    lines = _dump_value(data, indent)
    return "\n".join(lines) + "\n"


def _dump_value(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_value(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                item_lines = _dump_value(item, indent + 2)
                if item_lines:
                    first = item_lines[0].lstrip()
                    lines.append(f"{prefix}- {first}")
                    lines.extend(item_lines[1:])
                else:
                    lines.append(f"{prefix}-")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_dump_value(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(value)}"]


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if any(char in text for char in ":#[]{}&*!|>'\"%@`") or text.strip() != text:
        return repr(text)
    return text
