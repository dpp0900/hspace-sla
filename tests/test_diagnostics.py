from __future__ import annotations

import subprocess as sp
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sla_launcher.config import LaunchConfig
from sla_launcher.diagnostics import collect_environment_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_collects_environment_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk = root / "sdk"
            adb = sdk / "platform-tools" / "adb"
            emulator = sdk / "emulator" / "emulator"
            node = root / "node"
            npm = root / "npm"
            appium_main = root / "node_modules" / "appium" / "build" / "lib" / "main.js"
            for path in (adb, emulator, node, npm, appium_main):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            config = LaunchConfig(
                appium_url="http://127.0.0.1:4723",
                start_appium=False,
                keep_appium_running=False,
                node_path=str(node),
                npm_path=str(npm),
                appium_main_script=str(appium_main),
                avd=None,
                serial=None,
                emulator_path=None,
                android_sdk_root=str(sdk),
                adb_path=None,
                device_name="Android Emulator",
                apk=None,
                app_package=None,
                app_activity=None,
                app_wait_activity=None,
                app_wait_package=None,
                no_reset=True,
                boot_timeout=240,
                server_timeout=45,
                launch_wait=0,
            )

            with (
                patch("sla_launcher.diagnostics.is_appium_server_ready", return_value=True),
                patch(
                    "sla_launcher.diagnostics.load_avd_definitions",
                    return_value=[SimpleNamespace(name="Pixel_API_35")],
                ),
                patch(
                    "sla_launcher.diagnostics.sp.run",
                    return_value=sp.CompletedProcess([], 0, stdout="uiautomator2", stderr=""),
                ),
            ):
                diagnostics = collect_environment_diagnostics(config)

        self.assertEqual(diagnostics["summary"]["status"], "ok")
        titles = {check["title"] for check in diagnostics["checks"]}
        self.assertIn("Appium 패키지", titles)
        self.assertIn("UiAutomator2 드라이버", titles)


if __name__ == "__main__":
    unittest.main()
