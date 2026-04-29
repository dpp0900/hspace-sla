from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .paths import default_sdk_root


@dataclass(frozen=True)
class LaunchConfig:
    appium_url: str
    start_appium: bool
    keep_appium_running: bool
    node_path: str | None
    npm_path: str | None
    appium_main_script: str | None
    avd: str | None
    serial: str | None
    emulator_path: str | None
    android_sdk_root: str
    adb_path: str | None
    device_name: str
    apk: str | None
    app_package: str | None
    app_activity: str | None
    app_wait_activity: str | None
    app_wait_package: str | None
    no_reset: bool
    boot_timeout: int
    server_timeout: int
    launch_wait: int
    emulator_args: tuple[str, ...] = field(default_factory=tuple)


def build_parser() -> argparse.ArgumentParser:
    sdk_root_default = os.getenv("ANDROID_SDK_ROOT") or os.getenv("ANDROID_HOME") or str(default_sdk_root())
    parser = argparse.ArgumentParser(
        description=(
            "Android Studio Emulator를 부팅하고 Appium으로 앱을 자동 실행합니다. "
            "APK 설치 실행과 이미 설치된 앱 실행을 모두 지원합니다."
        )
    )
    parser.add_argument(
        "--appium-url",
        default=os.getenv("APPIUM_URL", "http://127.0.0.1:4723"),
        help="Appium 서버 URL",
    )
    parser.add_argument(
        "--start-appium",
        action="store_true",
        help="Appium 서버가 없으면 Python AppiumService로 자동 실행합니다.",
    )
    parser.add_argument(
        "--keep-appium-running",
        action="store_true",
        help="스크립트가 Python으로 시작한 Appium 서버를 종료하지 않습니다.",
    )
    parser.add_argument(
        "--node-path",
        default=os.getenv("APPIUM_NODE_PATH"),
        help="Node.js 실행 파일 경로. 지정하지 않으면 PATH에서 자동 탐색합니다.",
    )
    parser.add_argument(
        "--npm-path",
        default=os.getenv("APPIUM_NPM_PATH"),
        help="npm 실행 파일 경로. 지정하지 않으면 PATH에서 자동 탐색합니다.",
    )
    parser.add_argument(
        "--appium-main-script",
        default=os.getenv("APPIUM_MAIN_SCRIPT"),
        help="Appium main.js 경로. 지정하지 않으면 설치된 Appium을 자동 탐색합니다.",
    )
    parser.add_argument(
        "--avd",
        default=os.getenv("ANDROID_AVD"),
        help="실행할 Android Emulator AVD 이름. 지정하지 않으면 호스트 아키텍처에 맞는 AVD를 자동 선택합니다.",
    )
    parser.add_argument(
        "--serial",
        default=os.getenv("ANDROID_SERIAL"),
        help="특정 에뮬레이터 시리얼을 직접 지정합니다. 예: emulator-5554",
    )
    parser.add_argument(
        "--emulator-path",
        default=os.getenv("ANDROID_EMULATOR_PATH"),
        help="Android Emulator 실행 파일 경로. 지정하지 않으면 SDK 경로 기준으로 자동 유도합니다.",
    )
    parser.add_argument(
        "--android-sdk-root",
        default=sdk_root_default,
        help="Android SDK 루트 경로",
    )
    parser.add_argument(
        "--adb-path",
        default=os.getenv("ANDROID_ADB_PATH"),
        help="adb 실행 파일 경로. 지정하지 않으면 SDK 경로 기준으로 자동 유도합니다.",
    )
    parser.add_argument(
        "--device-name",
        default=os.getenv("ANDROID_DEVICE_NAME", "Android Emulator"),
        help="Appium capability의 deviceName 값",
    )
    parser.add_argument(
        "--apk",
        default=os.getenv("APK_PATH"),
        help="설치 후 실행할 APK 파일 경로",
    )
    parser.add_argument(
        "--app-package",
        default=os.getenv("APP_PACKAGE"),
        help="실행할 앱의 package 이름",
    )
    parser.add_argument(
        "--app-activity",
        default=os.getenv("APP_ACTIVITY"),
        help="실행할 앱의 main activity",
    )
    parser.add_argument(
        "--app-wait-activity",
        default=os.getenv("APP_WAIT_ACTIVITY"),
        help="스플래시 화면이 있는 경우 대기할 activity 패턴",
    )
    parser.add_argument(
        "--app-wait-package",
        default=os.getenv("APP_WAIT_PACKAGE"),
        help="앱 실행 후 다른 package 화면으로 전환될 수 있을 때 대기할 package 패턴",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="앱 데이터를 유지합니다.",
    )
    parser.add_argument(
        "--boot-timeout",
        type=int,
        default=int(os.getenv("ANDROID_BOOT_TIMEOUT", "240")),
        help="에뮬레이터 부팅 대기 시간(초)",
    )
    parser.add_argument(
        "--server-timeout",
        type=int,
        default=int(os.getenv("APPIUM_SERVER_TIMEOUT", "45")),
        help="Appium 서버 준비 대기 시간(초)",
    )
    parser.add_argument(
        "--launch-wait",
        type=int,
        default=int(os.getenv("APP_LAUNCH_WAIT", "5")),
        help="앱 실행 후 유지할 시간(초)",
    )
    parser.add_argument(
        "--emulator-arg",
        action="append",
        default=[],
        help='에뮬레이터 실행 시 추가 인자. 예: --emulator-arg "-no-snapshot-load"',
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.apk and not (args.app_package and args.app_activity):
        parser.error("--apk 또는 --app-package/--app-activity 조합이 필요합니다.")

    if args.apk:
        apk_path = Path(args.apk).expanduser().resolve()
        if not apk_path.exists():
            parser.error(f"APK 파일을 찾을 수 없습니다: {apk_path}")
        args.apk = str(apk_path)


def parse_args(argv: Sequence[str] | None = None) -> LaunchConfig:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    return LaunchConfig(
        appium_url=args.appium_url,
        start_appium=args.start_appium,
        keep_appium_running=args.keep_appium_running,
        node_path=args.node_path,
        npm_path=args.npm_path,
        appium_main_script=args.appium_main_script,
        avd=args.avd,
        serial=args.serial,
        emulator_path=args.emulator_path,
        android_sdk_root=args.android_sdk_root,
        adb_path=args.adb_path,
        device_name=args.device_name,
        apk=args.apk,
        app_package=args.app_package,
        app_activity=args.app_activity,
        app_wait_activity=args.app_wait_activity,
        app_wait_package=args.app_wait_package,
        no_reset=args.no_reset,
        boot_timeout=args.boot_timeout,
        server_timeout=args.server_timeout,
        launch_wait=args.launch_wait,
        emulator_args=tuple(args.emulator_arg),
    )
