from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .console import fail
from .process import run_command

if TYPE_CHECKING:
    from .config import LaunchConfig


def build_capabilities(config: LaunchConfig, serial: str) -> dict[str, object]:
    capabilities: dict[str, object] = {
        "platformName": "Android",
        "automationName": "UiAutomator2",
        "deviceName": config.device_name,
        "udid": serial,
        "autoGrantPermissions": True,
        "newCommandTimeout": 180,
        "noReset": config.no_reset,
        "eventTimings": True,
    }

    if config.apk:
        capabilities["app"] = config.apk
        capabilities["enforceAppInstall"] = True
    elif config.app_package and config.app_activity:
        capabilities["appPackage"] = config.app_package
        capabilities["appActivity"] = config.app_activity
        capabilities["autoLaunch"] = False

    if config.app_wait_activity:
        capabilities["appWaitActivity"] = config.app_wait_activity
    if config.app_wait_package:
        capabilities["appWaitPackage"] = config.app_wait_package

    return capabilities


def requires_manual_installed_launch(config: LaunchConfig) -> bool:
    return bool(config.app_package and config.app_activity and not config.apk)


def launch_installed_app(
    adb_path: str,
    serial: str,
    package: str,
    activity: str,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            adb_path,
            "-s",
            serial,
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            _component_name(package, activity),
        ],
        timeout=30,
    )


def _component_name(package: str, activity: str) -> str:
    return f"{package}/{activity}"


def create_driver(appium_url: str, capabilities: dict[str, object]):
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as exc:
        fail("필수 패키지가 없습니다. 먼저 `pip install -r requirements.txt`를 실행하세요.")
        raise exc

    options = UiAutomator2Options().load_capabilities(capabilities)
    return webdriver.Remote(appium_url, options=options)
