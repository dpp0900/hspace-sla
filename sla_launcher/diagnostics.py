from __future__ import annotations

import shutil
import subprocess as sp
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .android import detect_host_architecture, load_avd_definitions
from .appium_server import (
    _discover_appium_main_script,
    _discover_executable,
    is_appium_server_ready,
)
from .config import LaunchConfig
from .paths import platform_executable_name, sdk_tool_path


@dataclass(frozen=True)
class DiagnosticCheck:
    key: str
    title: str
    status: str
    message: str
    detail: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
        }


def collect_environment_diagnostics(config: LaunchConfig) -> dict[str, Any]:
    sdk_root = Path(config.android_sdk_root).expanduser()
    adb_hint = config.adb_path or sdk_tool_path(
        sdk_root,
        "platform-tools",
        platform_executable_name("adb"),
    )
    emulator_hint = config.emulator_path or sdk_tool_path(
        sdk_root,
        "emulator",
        platform_executable_name("emulator"),
    )
    node_path = _discover_executable(config.node_path, "node")
    npm_path = _discover_executable(config.npm_path, "npm")
    appium_main = _discover_appium_main_script(config.appium_main_script, npm_path)

    checks = [
        _path_check(
            "android_sdk",
            "Android SDK",
            sdk_root,
            ok_message="SDK 경로를 찾았습니다.",
            fail_message="SDK 경로를 찾지 못했습니다. ANDROID_SDK_ROOT 또는 ANDROID_HOME을 확인하세요.",
        ),
        _path_check(
            "adb",
            "ADB",
            Path(adb_hint).expanduser(),
            fallback=shutil.which(platform_executable_name("adb")),
            ok_message="adb 실행 파일을 찾았습니다.",
            fail_message="adb 실행 파일을 찾지 못했습니다.",
        ),
        _path_check(
            "emulator",
            "Android Emulator",
            Path(emulator_hint).expanduser(),
            fallback=shutil.which(platform_executable_name("emulator")),
            ok_message="emulator 실행 파일을 찾았습니다.",
            fail_message="emulator 실행 파일을 찾지 못했습니다.",
        ),
        _path_check(
            "node",
            "Node.js",
            Path(node_path).expanduser() if node_path else None,
            ok_message="Node.js 실행 파일을 찾았습니다.",
            fail_message="Node.js 실행 파일을 찾지 못했습니다.",
        ),
        _path_check(
            "npm",
            "npm",
            Path(npm_path).expanduser() if npm_path else None,
            ok_message="npm 실행 파일을 찾았습니다.",
            fail_message="npm 실행 파일을 찾지 못했습니다.",
        ),
        _path_check(
            "appium_main",
            "Appium 패키지",
            Path(appium_main).expanduser() if appium_main else None,
            ok_message="Appium main.js를 찾았습니다.",
            fail_message="Appium 패키지를 찾지 못했습니다. npm install appium 또는 APPIUM_MAIN_SCRIPT를 확인하세요.",
        ),
        _appium_server_check(config.appium_url),
        _avd_check(config),
        _uiautomator2_check(node_path, appium_main),
    ]
    status_counts = {
        "ok": sum(1 for check in checks if check.status == "ok"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "fail": sum(1 for check in checks if check.status == "fail"),
    }
    summary_status = "fail" if status_counts["fail"] else "warn" if status_counts["warn"] else "ok"
    return {
        "host_arch": detect_host_architecture(),
        "summary": {"status": summary_status, **status_counts},
        "checks": [check.to_dict() for check in checks],
    }


def _path_check(
    key: str,
    title: str,
    path: Path | None,
    *,
    ok_message: str,
    fail_message: str,
    fallback: str | None = None,
) -> DiagnosticCheck:
    if path and path.exists():
        return DiagnosticCheck(key, title, "ok", ok_message, str(path))
    if fallback:
        return DiagnosticCheck(key, title, "ok", ok_message, fallback)
    return DiagnosticCheck(key, title, "fail", fail_message, str(path) if path else None)


def _appium_server_check(appium_url: str) -> DiagnosticCheck:
    if is_appium_server_ready(appium_url):
        return DiagnosticCheck(
            "appium_server",
            "Appium 서버",
            "ok",
            "실행 중인 Appium 서버에 연결했습니다.",
            appium_url,
        )
    return DiagnosticCheck(
        "appium_server",
        "Appium 서버",
        "warn",
        "현재 서버는 꺼져 있습니다. 테스트 실행 시 자동 시작을 시도합니다.",
        appium_url,
    )


def _avd_check(config: LaunchConfig) -> DiagnosticCheck:
    if config.serial:
        return DiagnosticCheck(
            "device",
            "테스트 기기",
            "ok",
            "지정된 Android 기기 시리얼을 사용합니다.",
            config.serial,
        )
    try:
        avds = load_avd_definitions()
    except Exception as exc:  # noqa: BLE001 - diagnostics should report the failure as data.
        return DiagnosticCheck(
            "avd",
            "AVD",
            "warn",
            "AVD 목록을 읽지 못했습니다.",
            str(exc),
        )
    if config.avd and any(avd.name == config.avd for avd in avds):
        return DiagnosticCheck("avd", "AVD", "ok", "지정된 AVD를 찾았습니다.", config.avd)
    if avds:
        names = ", ".join(avd.name for avd in avds[:5])
        return DiagnosticCheck("avd", "AVD", "ok", "사용 가능한 AVD를 찾았습니다.", names)
    return DiagnosticCheck(
        "avd",
        "AVD",
        "warn",
        "사용 가능한 AVD를 찾지 못했습니다. 실제 기기를 쓰려면 ANDROID_SERIAL을 지정하세요.",
    )


def _uiautomator2_check(node_path: str | None, appium_main: str | None) -> DiagnosticCheck:
    if not node_path or not appium_main:
        return DiagnosticCheck(
            "uiautomator2",
            "UiAutomator2 드라이버",
            "warn",
            "Node.js 또는 Appium 패키지를 찾지 못해 드라이버 설치 여부를 확인하지 못했습니다.",
        )
    try:
        result = sp.run(
            [node_path, appium_main, "driver", "list", "--installed"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, sp.TimeoutExpired) as exc:
        return DiagnosticCheck(
            "uiautomator2",
            "UiAutomator2 드라이버",
            "warn",
            "Appium 드라이버 목록을 확인하지 못했습니다.",
            str(exc),
        )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0:
        return DiagnosticCheck(
            "uiautomator2",
            "UiAutomator2 드라이버",
            "warn",
            "Appium 드라이버 목록 명령이 실패했습니다.",
            output,
        )
    if "uiautomator2" in output.lower():
        return DiagnosticCheck(
            "uiautomator2",
            "UiAutomator2 드라이버",
            "ok",
            "Android 자동화 드라이버가 설치되어 있습니다.",
            "uiautomator2",
        )
    return DiagnosticCheck(
        "uiautomator2",
        "UiAutomator2 드라이버",
        "fail",
        "Android 자동화 드라이버가 설치되어 있지 않습니다. appium driver install uiautomator2를 실행하세요.",
        output or None,
    )
