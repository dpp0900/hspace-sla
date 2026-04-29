from __future__ import annotations

import time
from typing import Sequence

from .android import ensure_emulator
from .appium_server import maybe_start_appium
from .config import parse_args
from .console import log
from .paths import platform_executable_name, sdk_tool_path
from .process import resolve_executable, resolve_sdk_root
from .session import build_capabilities, create_driver, launch_installed_app, requires_manual_installed_launch


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    sdk_root = resolve_sdk_root(config.android_sdk_root)
    adb_hint = config.adb_path or sdk_tool_path(sdk_root, "platform-tools", platform_executable_name("adb"))
    adb_path = resolve_executable(adb_hint, platform_executable_name("adb"))

    appium_service = None
    driver = None

    try:
        serial = ensure_emulator(config, adb_path)
        appium_service = maybe_start_appium(config)
        capabilities = build_capabilities(config, serial)

        log("Appium 세션 생성 중...")
        driver = create_driver(config.appium_url, capabilities)
        if requires_manual_installed_launch(config):
            log("설치된 앱을 adb am start로 실행 중...")
            launch_installed_app(adb_path, serial, config.app_package or "", config.app_activity or "")

        current_package = getattr(driver, "current_package", None)
        if callable(current_package):
            current_package = current_package()
        log(f"앱 실행 완료. current_package={current_package or 'unknown'}")

        if config.launch_wait > 0:
            log(f"{config.launch_wait}초 동안 앱 상태 유지")
            time.sleep(config.launch_wait)

        return 0
    finally:
        if driver is not None:
            driver.quit()
            log("Appium 세션 종료")

        if appium_service is not None and not config.keep_appium_running:
            appium_service.stop()
            log("Python AppiumService로 시작한 서버 종료")
