from __future__ import annotations

from typing import TYPE_CHECKING

from .console import fail

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
    }

    if config.apk:
        capabilities["app"] = config.apk
    else:
        capabilities["appPackage"] = config.app_package
        capabilities["appActivity"] = config.app_activity

    if config.app_wait_activity:
        capabilities["appWaitActivity"] = config.app_wait_activity

    return capabilities


def create_driver(appium_url: str, capabilities: dict[str, object]):
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as exc:
        fail("필수 패키지가 없습니다. 먼저 `pip install -r requirements.txt`를 실행하세요.")
        raise exc

    options = UiAutomator2Options().load_capabilities(capabilities)
    return webdriver.Remote(appium_url, options=options)
