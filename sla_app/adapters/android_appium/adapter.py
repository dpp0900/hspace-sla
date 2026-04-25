from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from sla_app.core.models import ActionStep, AppTarget, TestSuite
from sla_launcher.android import ensure_emulator
from sla_launcher.appium_server import maybe_start_appium
from sla_launcher.config import LaunchConfig
from sla_launcher.paths import default_sdk_root, platform_executable_name, sdk_tool_path
from sla_launcher.process import resolve_executable, resolve_sdk_root
from sla_launcher.session import build_capabilities, create_driver


class AndroidAppiumAdapter:
    def __init__(self, config: LaunchConfig) -> None:
        self.config = config
        self.driver: Any = None
        self.appium_service: Any = None
        self._last_metrics: dict[str, float] = {}

    @classmethod
    def from_suite(cls, suite: TestSuite) -> "AndroidAppiumAdapter":
        return cls(_launch_config_from_target(suite.app, suite.source_path))

    def launch_app(self) -> None:
        if self.driver is not None:
            return

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

    def tap(self, step: ActionStep) -> None:
        self._element(step).click()

    def input(self, step: ActionStep) -> None:
        element = self._element(step)
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(str(step.value))

    def wait(self, step: ActionStep) -> None:
        time.sleep((step.timeout_ms or 1000) / 1000)

    def assert_text(self, step: ActionStep) -> None:
        self._ensure_driver()
        text = step.text or ""
        if text not in str(self.driver.page_source):
            raise AssertionError(f"text not found: {text}")

    def assert_exists(self, step: ActionStep) -> None:
        self._element(step)

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
        if current_package:
            metrics.update(self._collect_meminfo(str(current_package)))
        self._last_metrics.update(metrics)
        return metrics

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

    def _collect_meminfo(self, package_name: str) -> dict[str, float]:
        try:
            result = self.driver.execute_script(
                "mobile: shell",
                {"command": "dumpsys", "args": ["meminfo", package_name]},
            )
        except Exception:
            return {}
        text = str(result)
        for line in text.splitlines():
            if "TOTAL PSS:" in line:
                parts = line.replace(":", " ").split()
                for item in parts:
                    if item.isdigit():
                        return {"memory_mb": round(int(item) / 1024, 2)}
        return {}

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
    try:
        from appium.webdriver.common.appiumby import AppiumBy
    except ImportError as exc:
        raise RuntimeError("Appium-Python-Client is required for Android execution") from exc

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


def _safe_file_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return safe.strip("-") or "screenshot"
