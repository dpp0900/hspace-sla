from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sla_launcher.appium_server import (
    _discover_appium_main_script,
    _format_appium_start_error,
    _normalize_appium_main_script,
    build_appium_env,
)


class AppiumServerTests(unittest.TestCase):
    def test_normalizes_non_cli_appium_module_to_main_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "node_modules" / "appium" / "build" / "lib"
            lib.mkdir(parents=True)
            appium_module = lib / "appium.js"
            main_script = lib / "main.js"
            appium_module.write_text("", encoding="utf-8")
            main_script.write_text("", encoding="utf-8")

            self.assertEqual(_normalize_appium_main_script(appium_module), str(main_script.resolve()))

    def test_discovers_home_local_appium_main_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            main_script = home / "node_modules" / "appium" / "build" / "lib" / "main.js"
            main_script.parent.mkdir(parents=True)
            main_script.write_text("", encoding="utf-8")

            with (
                patch.object(Path, "home", return_value=home),
                patch("sla_launcher.appium_server._npm_module_roots", return_value=[]),
            ):
                self.assertEqual(_discover_appium_main_script(None, None), str(main_script.resolve()))

    def test_appium_env_includes_local_node_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdk_root = Path(tmp)
            with patch.object(Path, "home", return_value=Path("/Users/example")):
                env = build_appium_env(str(sdk_root))

        paths = env["PATH"].split(":")
        self.assertIn("/Users/example/node_modules/.bin", paths)
        self.assertIn(str(sdk_root / "platform-tools"), paths)

    def test_formats_empty_appium_service_error(self) -> None:
        message = _format_appium_start_error(Exception("b''"))

        self.assertIn("Appium 실행 로그가 비어 있습니다", message)


if __name__ == "__main__":
    unittest.main()
