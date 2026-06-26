from __future__ import annotations

import os
import re
import time
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from sla_app.core.models import ActionStep, AppTarget, TestSuite
from sla_launcher.android import ensure_emulator
from sla_launcher.appium_server import maybe_start_appium
from sla_launcher.config import LaunchConfig
from sla_launcher.paths import default_sdk_root, platform_executable_name, sdk_tool_path
from sla_launcher.process import resolve_executable, resolve_sdk_root
from sla_launcher.session import (
    build_capabilities,
    create_driver,
    launch_installed_app,
    requires_manual_installed_launch,
)

from .inspector import extract_ui_elements


class AndroidAppiumAdapter:
    def __init__(self, config: LaunchConfig) -> None:
        self.config = config
        self.driver: Any = None
        self.appium_service: Any = None
        self._last_metrics: dict[str, float] = {}
        self._last_launch_time_ms: int | None = None

    @classmethod
    def from_suite(cls, suite: TestSuite) -> "AndroidAppiumAdapter":
        return cls(_launch_config_from_target(suite.app, suite.source_path))

    def launch_app(self) -> None:
        if self.driver is not None:
            return

        started = time.monotonic()
        launch_output = ""
        sdk_root = resolve_sdk_root(self.config.android_sdk_root)
        adb_hint = self.config.adb_path or sdk_tool_path(
            sdk_root,
            "platform-tools",
            platform_executable_name("adb"),
        )
        adb_path = resolve_executable(adb_hint, platform_executable_name("adb"))
        serial = ensure_emulator(self.config, adb_path)
        self.appium_service = maybe_start_appium(self.config)
        capabilities = build_capabilities(self.config, serial)
        self.driver = create_driver(self.config.appium_url, capabilities)
        if requires_manual_installed_launch(self.config):
            result = launch_installed_app(
                adb_path,
                serial,
                self.config.app_package or "",
                self.config.app_activity or "",
            )
            launch_output = result.stdout or ""
        parsed_launch_time = _parse_am_start_total_time(launch_output)
        self._last_launch_time_ms = (
            parsed_launch_time
            if parsed_launch_time is not None
            else int((time.monotonic() - started) * 1000)
        )

    def tap(self, step: ActionStep) -> None:
        self._element(step).click()

    def activate_app(self, step: ActionStep) -> None:
        self._ensure_driver()
        package_name = self._target_package(step)
        started = time.monotonic()
        self.driver.activate_app(package_name)
        self._last_launch_time_ms = int((time.monotonic() - started) * 1000)

    def terminate_app(self, step: ActionStep) -> None:
        self._ensure_driver()
        self.driver.terminate_app(self._target_package(step))

    def background_app(self, step: ActionStep) -> None:
        self._ensure_driver()
        seconds = (step.timeout_ms or 1000) / 1000
        self.driver.background_app(seconds)

    def input(self, step: ActionStep) -> None:
        element = self._element(step)
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(str(step.value))

    def back(self, step: ActionStep) -> None:
        self._ensure_driver()
        self.driver.back()

    def swipe(self, step: ActionStep) -> None:
        self._gesture(step, command="swipeGesture", default_direction="up", default_percent=0.75)

    def scroll(self, step: ActionStep) -> None:
        self._gesture(step, command="scrollGesture", default_direction="down", default_percent=1.0)

    def scroll_to_text(self, step: ActionStep) -> None:
        self._ensure_driver()
        text = step.text or ""
        timeout = (step.timeout_ms or 8000) / 1000
        deadline = time.time() + timeout
        last_error: Exception | None = None
        by = _appium_by()
        selector = (
            "new UiScrollable(new UiSelector().scrollable(true))"
            f".scrollIntoView(new UiSelector().textContains(\"{_escape_java_string(text)}\"))"
        )
        while time.time() <= deadline:
            try:
                self.driver.find_element(by.ANDROID_UIAUTOMATOR, selector)
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        raise AssertionError(f"text not found after scroll: {text}") from last_error

    def wait(self, step: ActionStep) -> None:
        time.sleep((step.timeout_ms or 1000) / 1000)

    def assert_text(self, step: ActionStep) -> None:
        self._ensure_driver()
        text = step.text or ""
        if text not in str(self.driver.page_source):
            raise AssertionError(f"text not found: {text}")

    def assert_not_text(self, step: ActionStep) -> None:
        self._ensure_driver()
        text = step.text or ""
        timeout = (step.timeout_ms or 5000) / 1000
        deadline = time.time() + timeout
        while True:
            if text not in str(self.driver.page_source):
                return
            if time.time() >= deadline:
                raise AssertionError(f"text still present: {text}")
            time.sleep(0.25)

    def assert_exists(self, step: ActionStep) -> None:
        self._element(step)

    def assert_not_exists(self, step: ActionStep) -> None:
        self._ensure_driver()
        timeout = (step.timeout_ms or 5000) / 1000
        deadline = time.time() + timeout
        while True:
            if not self._element_present(step):
                return
            if time.time() >= deadline:
                raise AssertionError(f"element still present: {step.selector or step.text}")
            time.sleep(0.25)

    def assert_visible(self, step: ActionStep) -> None:
        element = self._element(step)
        if not element.is_displayed():
            raise AssertionError(f"element not visible: {step.selector or step.text}")

    def assert_enabled(self, step: ActionStep) -> None:
        element = self._element(step)
        if not element.is_enabled():
            raise AssertionError(f"element not enabled: {step.selector or step.text}")

    def assert_attribute(self, step: ActionStep) -> None:
        element = self._element(step)
        attribute = step.attribute or ""
        actual = element.get_attribute(attribute)
        expected = "" if step.value is None else str(step.value)
        if str(actual) != expected:
            raise AssertionError(
                f"attribute {attribute} expected {expected}, got {actual}"
            )

    def assert_current_package(self, step: ActionStep) -> None:
        self._ensure_driver()
        expected = step.package or (str(step.value) if step.value is not None else "")
        actual = self._current_package()
        if not actual or not _matches_expected(actual, expected):
            raise AssertionError(f"package expected {expected}, got {actual or 'unknown'}")

    def assert_current_activity(self, step: ActionStep) -> None:
        self._ensure_driver()
        expected = step.activity or (str(step.value) if step.value is not None else "")
        actual = self._current_activity()
        if not actual or not _matches_expected(actual, expected):
            raise AssertionError(f"activity expected {expected}, got {actual or 'unknown'}")

    def screenshot(self, step: ActionStep, artifact_dir: Path) -> str:
        self._ensure_driver()
        name = step.name or f"screenshot-{int(time.time() * 1000)}"
        path = artifact_dir / f"{_safe_file_name(name)}.png"
        self.driver.save_screenshot(str(path))
        return str(path)

    def collect_metrics(self, step: ActionStep) -> dict[str, float]:
        self._ensure_driver()
        metrics: dict[str, float] = {}
        current_package = getattr(self.driver, "current_package", None)
        if callable(current_package):
            current_package = current_package()
        current_package = current_package or self.config.app_package
        if self._last_launch_time_ms is not None:
            metrics["launch_time_ms"] = self._last_launch_time_ms
        if current_package:
            package_name = str(current_package)
            metrics.update(self._collect_meminfo(package_name))
            cpu_percent = self._collect_cpu_percent(package_name)
            if cpu_percent is not None:
                metrics["cpu_percent"] = cpu_percent
            logcat_errors = self._collect_logcat_errors(package_name)
            if logcat_errors is not None:
                metrics["logcat_error_count"] = logcat_errors
        metrics.update(self._collect_event_timing_metrics())
        self._last_metrics.update(metrics)
        return metrics

    def inspect_elements(self, mode: str = "standard") -> list[dict[str, str]]:
        self._ensure_driver()
        return extract_ui_elements(str(self.driver.page_source), mode=mode)

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
        if self.appium_service is not None and not self.config.keep_appium_running:
            self.appium_service.stop()
            self.appium_service = None

    def _element(self, step: ActionStep):
        self._ensure_driver()
        by, value = _locator(step)
        timeout = (step.timeout_ms or 5000) / 1000
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() <= deadline:
            try:
                return self.driver.find_element(by, value)
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        raise AssertionError(f"element not found: {step.selector or step.text}") from last_error

    def _element_present(self, step: ActionStep) -> bool:
        by, value = _locator(step)
        try:
            self.driver.find_element(by, value)
            return True
        except Exception:
            return False

    def _target_package(self, step: ActionStep) -> str:
        package_name = (
            step.package
            or (str(step.value) if step.value is not None else None)
            or self._current_package()
            or self.config.app_package
        )
        if not package_name:
            raise AssertionError("app package is unavailable")
        return str(package_name)

    def _current_package(self) -> str | None:
        value = getattr(self.driver, "current_package", None)
        if callable(value):
            value = value()
        return str(value) if value else None

    def _current_activity(self) -> str | None:
        value = getattr(self.driver, "current_activity", None)
        if callable(value):
            value = value()
        return str(value) if value else None

    def _gesture(
        self,
        step: ActionStep,
        *,
        command: str,
        default_direction: str,
        default_percent: float,
    ) -> None:
        self._ensure_driver()
        args: dict[str, object] = {
            "direction": _gesture_direction(step.direction or step.value, default_direction),
            "percent": step.percent if step.percent is not None else default_percent,
        }
        if step.selector or step.text:
            element = self._element(step)
            element_id = _element_id(element)
            if element_id:
                args["elementId"] = element_id
            else:
                args.update(_rect_bounds(getattr(element, "rect", None)))
        else:
            args.update(_window_gesture_bounds(self.driver))
        self.driver.execute_script(f"mobile: {command}", args)

    def _collect_meminfo(self, package_name: str) -> dict[str, float]:
        text = self._shell("dumpsys", ["meminfo", package_name], timeout=5000)
        pss_kb = _parse_meminfo_total_pss_kb(text)
        if pss_kb is not None:
            return {"memory_mb": round(pss_kb / 1024, 2)}
        return {}

    def _collect_cpu_percent(self, package_name: str) -> float | None:
        text = self._shell("dumpsys", ["cpuinfo"], timeout=5000)
        return _parse_cpu_percent(text, package_name)

    def _collect_logcat_errors(self, package_name: str) -> int | None:
        pid_text = self._shell("pidof", [package_name], timeout=3000)
        pids = _parse_pids(pid_text)
        if not pids:
            return None
        log_text = self._shell("logcat", ["-d", "-t", "500", "-v", "threadtime"], timeout=8000)
        return _count_logcat_errors(log_text, pids)

    def _collect_event_timing_metrics(self) -> dict[str, float]:
        try:
            get_events = getattr(self.driver, "get_events", None)
            events = get_events() if callable(get_events) else getattr(self.driver, "events", None)
        except Exception:
            return {}
        return _event_timing_metrics(events)

    def _shell(self, command: str, args: list[str], *, timeout: int) -> str:
        try:
            result = self.driver.execute_script(
                "mobile: shell",
                {"command": command, "args": args, "timeout": timeout},
            )
        except Exception:
            return ""
        if isinstance(result, dict):
            return str(result.get("stdout") or "")
        return str(result or "")

    def _ensure_driver(self) -> None:
        if self.driver is None:
            self.launch_app()


def _launch_config_from_target(target: AppTarget, source_path: Path | None) -> LaunchConfig:
    sdk_root_default = os.getenv("ANDROID_SDK_ROOT") or os.getenv("ANDROID_HOME") or str(default_sdk_root())
    apk = _resolve_relative_path(target.apk, source_path) if target.apk else None
    return LaunchConfig(
        appium_url=os.getenv("APPIUM_URL", "http://127.0.0.1:4723"),
        start_appium=os.getenv("SLA_START_APPIUM", "true").lower() in {"1", "true", "yes"},
        keep_appium_running=os.getenv("SLA_KEEP_APPIUM_RUNNING", "").lower() in {"1", "true", "yes"},
        node_path=os.getenv("APPIUM_NODE_PATH"),
        npm_path=os.getenv("APPIUM_NPM_PATH"),
        appium_main_script=os.getenv("APPIUM_MAIN_SCRIPT"),
        avd=os.getenv("ANDROID_AVD"),
        serial=os.getenv("ANDROID_SERIAL"),
        emulator_path=os.getenv("ANDROID_EMULATOR_PATH"),
        android_sdk_root=sdk_root_default,
        adb_path=os.getenv("ANDROID_ADB_PATH"),
        device_name=os.getenv("ANDROID_DEVICE_NAME", "Android Emulator"),
        apk=apk,
        app_package=target.app_package,
        app_activity=target.app_activity,
        app_wait_activity=target.app_wait_activity,
        app_wait_package=target.app_wait_package,
        no_reset=target.no_reset,
        boot_timeout=int(os.getenv("ANDROID_BOOT_TIMEOUT", "240")),
        server_timeout=int(os.getenv("APPIUM_SERVER_TIMEOUT", "45")),
        launch_wait=0,
        emulator_args=tuple(filter(None, os.getenv("ANDROID_EMULATOR_ARGS", "").split())),
    )


def _resolve_relative_path(path: str, source_path: Path | None) -> str:
    expanded = Path(path).expanduser()
    if expanded.is_absolute() or source_path is None:
        return str(expanded)
    suite_relative = (source_path.parent / expanded).resolve()
    if suite_relative.exists():
        return str(suite_relative)
    return str(expanded.resolve())


def _locator(step: ActionStep) -> tuple[str, str]:
    AppiumBy = _appium_by()

    if step.text:
        xpath = f'//*[@text="{step.text}" or contains(@text, "{step.text}")]'
        return AppiumBy.XPATH, xpath

    selector = step.selector or ""
    if "=" in selector:
        strategy, value = selector.split("=", 1)
        strategy = strategy.strip().lower()
        value = value.strip()
        if strategy in {"id", "resource-id"}:
            return AppiumBy.ID, value
        if strategy in {"accessibility_id", "accessibility-id", "a11y"}:
            return AppiumBy.ACCESSIBILITY_ID, value
        if strategy == "xpath":
            return AppiumBy.XPATH, value
        if strategy in {"uiautomator", "android_uiautomator"}:
            return AppiumBy.ANDROID_UIAUTOMATOR, value

    if selector.startswith("/"):
        return AppiumBy.XPATH, selector
    return AppiumBy.ID, selector


def _appium_by():
    try:
        from appium.webdriver.common.appiumby import AppiumBy
    except ImportError as exc:
        raise RuntimeError("Appium-Python-Client is required for Android execution") from exc
    return AppiumBy


def _gesture_direction(value: object, default: str) -> str:
    direction = str(value or default).strip().lower()
    if direction not in {"up", "down", "left", "right"}:
        raise AssertionError(f"unsupported gesture direction: {direction}")
    return direction


def _element_id(element) -> str | None:
    element_id = getattr(element, "id", None) or getattr(element, "_id", None)
    if element_id:
        return str(element_id)
    return None


def _rect_bounds(rect: object) -> dict[str, int]:
    if not isinstance(rect, dict):
        raise AssertionError("gesture target has no usable bounds")
    return {
        "left": int(rect.get("x", 0)),
        "top": int(rect.get("y", 0)),
        "width": max(1, int(rect.get("width", 1))),
        "height": max(1, int(rect.get("height", 1))),
    }


def _window_gesture_bounds(driver) -> dict[str, int]:
    size = driver.get_window_size()
    width = int(size.get("width", 0))
    height = int(size.get("height", 0))
    if width <= 0 or height <= 0:
        raise AssertionError("device window size is unavailable")
    return {
        "left": int(width * 0.05),
        "top": int(height * 0.05),
        "width": max(1, int(width * 0.9)),
        "height": max(1, int(height * 0.85)),
    }


def _escape_java_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _parse_am_start_total_time(output: str) -> int | None:
    match = re.search(r"\bTotalTime:\s*(\d+)", output)
    if match:
        return int(match.group(1))
    return None


def _parse_meminfo_total_pss_kb(output: str) -> int | None:
    match = re.search(r"\bTOTAL\s+PSS:\s*(\d+)", output)
    if match:
        return int(match.group(1))
    return None


def _parse_cpu_percent(output: str, package_name: str) -> float | None:
    total = 0.0
    matched = False
    for line in output.splitlines():
        match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)%\s+\d+/([^:\s]+)", line)
        if not match:
            continue
        process_name = match.group(2)
        if process_name == package_name or process_name.startswith(f"{package_name}:"):
            matched = True
            total += float(match.group(1))
    if not matched:
        return None
    return round(total, 2)


def _parse_pids(output: str) -> set[str]:
    return {item for item in output.split() if item.isdigit()}


def _count_logcat_errors(output: str, pids: set[str]) -> int:
    count = 0
    for line in output.splitlines():
        parts = line.split(maxsplit=6)
        if len(parts) < 5:
            continue
        pid = parts[2]
        priority = parts[4]
        if pid in pids and priority in {"E", "F"}:
            count += 1
    return count


def _event_timing_metrics(events: object) -> dict[str, float]:
    if not isinstance(events, dict):
        return {}

    metrics: dict[str, float] = {}
    command_durations = _command_durations_ms(events.get("commands"))
    if command_durations:
        metrics["appium_command_count"] = float(len(command_durations))
        metrics["appium_command_avg_ms"] = round(sum(command_durations) / len(command_durations), 2)
        metrics["appium_command_max_ms"] = round(max(command_durations), 2)

    new_session_ms = _event_span_ms(events, "newSessionRequested", "newSessionStarted")
    if new_session_ms is not None:
        metrics["appium_new_session_ms"] = new_session_ms
    return metrics


def _command_durations_ms(commands: object) -> list[float]:
    if not isinstance(commands, list):
        return []
    durations: list[float] = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        started = _numeric(command.get("startTime"))
        ended = _numeric(command.get("endTime"))
        if started is None or ended is None or ended < started:
            continue
        durations.append(round(ended - started, 2))
    return durations


def _event_span_ms(events: dict[str, object], start_name: str, end_name: str) -> float | None:
    started = _first_numeric(events.get(start_name))
    ended = _first_numeric(events.get(end_name))
    if started is None or ended is None or ended < started:
        return None
    return round(ended - started, 2)


def _first_numeric(value: object) -> float | None:
    if isinstance(value, list):
        for item in value:
            parsed = _numeric(item)
            if parsed is not None:
                return parsed
        return None
    return _numeric(value)


def _numeric(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches_expected(actual: str, expected: str) -> bool:
    return fnmatchcase(actual, expected) if any(char in expected for char in "*?[]") else actual == expected


def _safe_file_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return safe.strip("-") or "screenshot"
