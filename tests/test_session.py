from __future__ import annotations

import unittest

from sla_launcher.config import LaunchConfig
from sla_launcher.session import build_capabilities


def _config(**overrides) -> LaunchConfig:
    values = {
        "appium_url": "http://127.0.0.1:4723",
        "start_appium": True,
        "keep_appium_running": False,
        "node_path": None,
        "npm_path": None,
        "appium_main_script": None,
        "avd": None,
        "serial": None,
        "emulator_path": None,
        "android_sdk_root": "/sdk",
        "adb_path": None,
        "device_name": "Android Emulator",
        "apk": None,
        "app_package": None,
        "app_activity": None,
        "app_wait_activity": None,
        "app_wait_package": None,
        "no_reset": False,
        "boot_timeout": 240,
        "server_timeout": 45,
        "launch_wait": 0,
        "emulator_args": (),
    }
    values.update(overrides)
    return LaunchConfig(**values)


class SessionTests(unittest.TestCase):
    def test_apk_capabilities_force_current_apk_install(self) -> None:
        capabilities = build_capabilities(_config(apk="/tmp/app.apk"), "emulator-5554")

        self.assertEqual(capabilities["app"], "/tmp/app.apk")
        self.assertTrue(capabilities["enforceAppInstall"])
        self.assertNotIn("autoLaunch", capabilities)

    def test_installed_app_capabilities_do_not_force_install(self) -> None:
        capabilities = build_capabilities(
            _config(app_package="com.example", app_activity=".MainActivity"),
            "emulator-5554",
        )

        self.assertEqual(capabilities["appPackage"], "com.example")
        self.assertFalse(capabilities["autoLaunch"])
        self.assertNotIn("enforceAppInstall", capabilities)

    def test_installed_app_wait_package_capability(self) -> None:
        capabilities = build_capabilities(
            _config(
                app_package="com.example",
                app_activity=".MainActivity",
                app_wait_activity="*",
                app_wait_package="*",
            ),
            "emulator-5554",
        )

        self.assertEqual(capabilities["appWaitActivity"], "*")
        self.assertEqual(capabilities["appWaitPackage"], "*")


if __name__ == "__main__":
    unittest.main()
