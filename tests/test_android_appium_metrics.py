from __future__ import annotations

import unittest

from sla_app.adapters.android_appium.adapter import (
    AndroidAppiumAdapter,
    _count_logcat_errors,
    _event_timing_metrics,
    _matches_expected,
    _parse_am_start_total_time,
    _parse_cpu_percent,
    _parse_meminfo_total_pss_kb,
    _parse_pids,
)
from sla_app.core.models import ActionStep
from sla_launcher.config import LaunchConfig


def _config() -> LaunchConfig:
    return LaunchConfig(
        appium_url="http://127.0.0.1:4723",
        start_appium=False,
        keep_appium_running=False,
        node_path=None,
        npm_path=None,
        appium_main_script=None,
        avd=None,
        serial=None,
        emulator_path=None,
        android_sdk_root="/sdk",
        adb_path=None,
        device_name="Android Emulator",
        apk=None,
        app_package="com.example",
        app_activity=".MainActivity",
        app_wait_activity=None,
        app_wait_package=None,
        no_reset=False,
        boot_timeout=240,
        server_timeout=45,
        launch_wait=0,
        emulator_args=(),
    )


class FakeMetricDriver:
    current_package = "com.example"
    events = {
        "newSessionRequested": [1000],
        "newSessionStarted": [1750],
        "commands": [
            {"cmd": "findElement", "startTime": 2000, "endTime": 2035},
            {"cmd": "click", "startTime": 2100, "endTime": 2130},
        ],
    }

    def execute_script(self, script: str, payload: dict[str, object]) -> str:
        self.last_script = script
        command = payload["command"]
        args = payload.get("args") or []
        if command == "dumpsys" and args[0] == "meminfo":
            return "TOTAL PSS: 81920"
        if command == "dumpsys" and args[0] == "cpuinfo":
            return "  7.5% 1234/com.example: 5% user + 2.5% kernel"
        if command == "pidof":
            return "1234"
        if command == "logcat":
            return "06-26 10:00:00.000  1234  1234 E Login   : failed"
        return ""


class FakeStateDriver:
    current_package = "com.example"
    current_activity = "com.example.MainActivity"
    page_source = '<hierarchy><node text="Home" /></hierarchy>'

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def activate_app(self, package_name: str) -> None:
        self.calls.append(("activate_app", package_name))

    def terminate_app(self, package_name: str) -> None:
        self.calls.append(("terminate_app", package_name))

    def background_app(self, seconds: float) -> None:
        self.calls.append(("background_app", seconds))

    def find_element(self, by: str, value: str):
        self.calls.append(("find_element", value))
        raise RuntimeError("not found")


class AndroidAppiumMetricsTests(unittest.TestCase):
    def test_collect_metrics_combines_runtime_signals(self) -> None:
        adapter = AndroidAppiumAdapter(_config())
        adapter.driver = FakeMetricDriver()
        adapter._last_launch_time_ms = 742

        metrics = adapter.collect_metrics(ActionStep(action="collect_metrics"))

        self.assertEqual(metrics["memory_mb"], 80)
        self.assertEqual(metrics["launch_time_ms"], 742)
        self.assertEqual(metrics["cpu_percent"], 7.5)
        self.assertEqual(metrics["logcat_error_count"], 1)
        self.assertEqual(metrics["appium_new_session_ms"], 750)
        self.assertEqual(metrics["appium_command_count"], 2)
        self.assertEqual(metrics["appium_command_avg_ms"], 32.5)
        self.assertEqual(metrics["appium_command_max_ms"], 35)

    def test_state_actions_and_assertions_use_current_app_context(self) -> None:
        adapter = AndroidAppiumAdapter(_config())
        driver = FakeStateDriver()
        adapter.driver = driver

        adapter.terminate_app(ActionStep(action="terminate_app"))
        adapter.activate_app(ActionStep(action="activate_app"))
        adapter.background_app(ActionStep(action="background_app", timeout_ms=1500))
        adapter.assert_current_package(
            ActionStep(action="assert_current_package", package="com.*")
        )
        adapter.assert_current_activity(
            ActionStep(action="assert_current_activity", activity="*.MainActivity")
        )
        adapter.assert_not_text(ActionStep(action="assert_not_text", text="Crash"))
        adapter.assert_not_exists(
            ActionStep(action="assert_not_exists", selector="id=com.example:id/error")
        )

        self.assertIn(("terminate_app", "com.example"), driver.calls)
        self.assertIn(("activate_app", "com.example"), driver.calls)
        self.assertIn(("background_app", 1.5), driver.calls)
        self.assertIsNotNone(adapter._last_launch_time_ms)

    def test_parses_am_start_total_time(self) -> None:
        output = """
Starting: Intent { cmp=com.example/.MainActivity }
Status: ok
LaunchState: COLD
Activity: com.example/.MainActivity
TotalTime: 742
WaitTime: 759
Complete
"""

        self.assertEqual(_parse_am_start_total_time(output), 742)

    def test_parses_meminfo_total_pss(self) -> None:
        output = """
Applications Memory Usage (in Kilobytes):
Uptime: 123 Realtime: 456
** MEMINFO in pid 1234 [com.example] **
TOTAL PSS: 81920
"""

        self.assertEqual(_parse_meminfo_total_pss_kb(output), 81920)

    def test_sums_cpu_for_package_processes(self) -> None:
        output = """
Load: 1.0 / 1.0 / 1.0
  7.5% 1234/com.example: 5% user + 2.5% kernel
  2.0% 1235/com.example:remote: 1% user + 1% kernel
  3.0% 9999/com.other: 1% user + 2% kernel
"""

        self.assertEqual(_parse_cpu_percent(output, "com.example"), 9.5)

    def test_counts_logcat_error_lines_for_app_pids(self) -> None:
        pids = _parse_pids("1234 1235")
        output = """
06-26 10:00:00.000  1234  1234 E Login   : failed
06-26 10:00:00.100  1234  1234 W Login   : warning
06-26 10:00:00.200  1235  1236 F Worker  : fatal
06-26 10:00:00.300  9999  9999 E Other   : ignored
"""

        self.assertEqual(_count_logcat_errors(output, pids), 2)

    def test_event_timing_metrics_ignore_invalid_entries(self) -> None:
        events = {
            "newSessionRequested": ["100"],
            "newSessionStarted": [250],
            "commands": [
                {"cmd": "findElement", "startTime": 300, "endTime": 350},
                {"cmd": "click", "startTime": 400, "endTime": 390},
                {"cmd": "back", "startTime": 500, "endTime": 525.5},
                "ignored",
            ],
        }

        self.assertEqual(
            _event_timing_metrics(events),
            {
                "appium_command_count": 2.0,
                "appium_command_avg_ms": 37.75,
                "appium_command_max_ms": 50.0,
                "appium_new_session_ms": 150.0,
            },
        )

    def test_matches_expected_supports_wildcards(self) -> None:
        self.assertTrue(_matches_expected("com.example.MainActivity", "*.MainActivity"))
        self.assertFalse(_matches_expected("com.example.Settings", "*.MainActivity"))


if __name__ == "__main__":
    unittest.main()
