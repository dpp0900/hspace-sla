#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen


DEFAULT_SDK_ROOT = Path.home() / "Library" / "Android" / "sdk"
DEFAULT_EMULATOR_PATH = DEFAULT_SDK_ROOT / "emulator" / "emulator"
DEFAULT_ADB_PATH = DEFAULT_SDK_ROOT / "platform-tools" / "adb"


def log(message: str) -> None:
    print(f"[INFO] {message}")


def fail(message: str, exit_code: int = 1) -> "NoReturn":
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def parse_args() -> argparse.Namespace:
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
        default=os.getenv("ANDROID_AVD", "Medium_Phone_API_36_ARM64"),
        help="실행할 Android Emulator AVD 이름",
    )
    parser.add_argument(
        "--serial",
        default=os.getenv("ANDROID_SERIAL"),
        help="특정 에뮬레이터 시리얼을 직접 지정합니다. 예: emulator-5554",
    )
    parser.add_argument(
        "--emulator-path",
        default=os.getenv("ANDROID_EMULATOR_PATH", str(DEFAULT_EMULATOR_PATH)),
        help="Android Emulator 실행 파일 경로",
    )
    parser.add_argument(
        "--android-sdk-root",
        default=os.getenv("ANDROID_SDK_ROOT") or os.getenv("ANDROID_HOME") or str(DEFAULT_SDK_ROOT),
        help="Android SDK 루트 경로",
    )
    parser.add_argument(
        "--adb-path",
        default=os.getenv("ANDROID_ADB_PATH", str(DEFAULT_ADB_PATH)),
        help="adb 실행 파일 경로",
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

    args = parser.parse_args()
    validate_args(args, parser)
    return args


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.apk and not (args.app_package and args.app_activity):
        parser.error("--apk 또는 --app-package/--app-activity 조합이 필요합니다.")

    if args.apk:
        apk_path = Path(args.apk).expanduser().resolve()
        if not apk_path.exists():
            parser.error(f"APK 파일을 찾을 수 없습니다: {apk_path}")
        args.apk = str(apk_path)


def run_command(
    command: Iterable[str],
    *,
    check: bool = True,
    capture_output: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=check,
        text=True,
        capture_output=capture_output,
        timeout=timeout,
    )


def resolve_executable(path_hint: str, command_name: str) -> str:
    expanded = str(Path(path_hint).expanduser())
    if Path(expanded).exists():
        return expanded

    found = shutil.which(command_name)
    if found:
        return found

    fail(f"{command_name} 실행 파일을 찾지 못했습니다. 경로를 확인하세요: {expanded}")


def resolve_sdk_root(path_hint: str) -> str:
    expanded = str(Path(path_hint).expanduser())
    if Path(expanded).exists():
        return expanded
    fail(f"Android SDK 경로를 찾지 못했습니다: {expanded}")


def adb_devices(adb_path: str) -> list[str]:
    result = run_command([adb_path, "devices"])
    devices: list[str] = []
    for line in result.stdout.splitlines():
        if "\tdevice" in line:
            devices.append(line.split("\t", 1)[0].strip())
    return devices


def emulator_devices(adb_path: str) -> list[str]:
    return [serial for serial in adb_devices(adb_path) if serial.startswith("emulator-")]


def wait_for_new_emulator(adb_path: str, known_serials: set[str], timeout: int) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = set(emulator_devices(adb_path))
        new_serials = sorted(current - known_serials)
        if new_serials:
            return new_serials[0]
        time.sleep(2)
    fail("새 에뮬레이터가 adb에 연결되지 않았습니다. AVD 실행 상태를 확인하세요.")


def wait_for_boot(adb_path: str, serial: str, timeout: int) -> None:
    log(f"{serial} 부팅 완료 대기 중...")
    run_command([adb_path, "-s", serial, "wait-for-device"], capture_output=False, timeout=timeout)

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = run_command([adb_path, "-s", serial, "shell", "getprop", "sys.boot_completed"])
            if result.stdout.strip() == "1":
                run_command(
                    [adb_path, "-s", serial, "shell", "input", "keyevent", "82"],
                    check=False,
                )
                log(f"{serial} 부팅 완료")
                return
        except subprocess.SubprocessError:
            pass
        time.sleep(3)

    fail(f"{serial} 부팅이 {timeout}초 안에 완료되지 않았습니다.")


def ensure_emulator(args: argparse.Namespace, adb_path: str) -> str:
    if args.serial:
        if args.serial not in adb_devices(adb_path):
            fail(f"지정한 시리얼이 연결되어 있지 않습니다: {args.serial}")
        wait_for_boot(adb_path, args.serial, args.boot_timeout)
        return args.serial

    running = emulator_devices(adb_path)
    if running:
        serial = running[0]
        log(f"이미 실행 중인 에뮬레이터 사용: {serial}")
        wait_for_boot(adb_path, serial, args.boot_timeout)
        return serial

    emulator_path = resolve_executable(args.emulator_path, "emulator")
    known_serials = set(running)
    launch_command = [emulator_path, f"@{args.avd}", *args.emulator_arg]

    log(f"AVD 실행: {args.avd}")
    subprocess.Popen(
        launch_command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    serial = wait_for_new_emulator(adb_path, known_serials, args.boot_timeout)
    wait_for_boot(adb_path, serial, args.boot_timeout)
    return serial


def is_appium_server_ready(appium_url: str) -> bool:
    status_url = urljoin(appium_url.rstrip("/") + "/", "status")
    try:
        with urlopen(status_url, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
            return bool(data.get("value") or data.get("status") == 0)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def wait_for_appium(appium_url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_appium_server_ready(appium_url):
            log(f"Appium 서버 연결 완료: {appium_url}")
            return
        time.sleep(2)
    fail(f"Appium 서버가 {timeout}초 안에 준비되지 않았습니다: {appium_url}")


def parse_appium_url(appium_url: str) -> tuple[str, int, str | None]:
    parsed = urlparse(appium_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4723
    base_path = parsed.path.strip() or None

    if base_path == "/":
        base_path = None

    return host, port, base_path


def build_appium_env(sdk_root: str) -> dict[str, str]:
    env = os.environ.copy()
    extra_paths = [
        str(Path(sdk_root) / "platform-tools"),
        str(Path(sdk_root) / "emulator"),
        str(Path(sdk_root) / "cmdline-tools" / "latest" / "bin"),
    ]
    env["ANDROID_HOME"] = sdk_root
    env["ANDROID_SDK_ROOT"] = sdk_root
    env["PATH"] = os.pathsep.join(extra_paths + [env.get("PATH", "")])
    return env


def maybe_start_appium(args: argparse.Namespace):
    if is_appium_server_ready(args.appium_url):
        log(f"기존 Appium 서버 사용: {args.appium_url}")
        return None

    if not args.start_appium:
        fail(
            "Appium 서버에 연결할 수 없습니다. 먼저 Appium을 실행하거나 "
            "--start-appium 옵션을 사용하세요."
        )

    try:
        from appium.webdriver.appium_service import AppiumService, AppiumServiceError
    except ImportError:
        fail("필수 패키지가 없습니다. 먼저 `pip install -r requirements.txt`를 실행하세요.")

    service = AppiumService()
    host, port, base_path = parse_appium_url(args.appium_url)
    service_args = ["--address", host, "--port", str(port)]

    if base_path:
        service_args.extend(["--base-path", base_path])

    start_kwargs: dict[str, object] = {
        "args": service_args,
        "env": build_appium_env(resolve_sdk_root(args.android_sdk_root)),
        "timeout_ms": args.server_timeout * 1000,
    }
    if args.node_path:
        start_kwargs["node"] = args.node_path
    if args.npm_path:
        start_kwargs["npm"] = args.npm_path
    if args.appium_main_script:
        start_kwargs["main_script"] = args.appium_main_script

    log(f"Python AppiumService로 서버 시작: {args.appium_url}")
    try:
        service.start(
            **start_kwargs,
        )
    except (AppiumServiceError, FileNotFoundError) as exc:
        fail(
            "Python AppiumService로 서버 시작에 실패했습니다. "
            "Appium 서버 패키지와 드라이버가 설치되어 있는지 확인하세요.\n"
            f"원인: {exc}"
        )
    wait_for_appium(args.appium_url, args.server_timeout)
    return service


def build_capabilities(args: argparse.Namespace, serial: str) -> dict[str, object]:
    caps: dict[str, object] = {
        "platformName": "Android",
        "automationName": "UiAutomator2",
        "deviceName": args.device_name,
        "udid": serial,
        "autoGrantPermissions": True,
        "newCommandTimeout": 180,
        "noReset": args.no_reset,
    }

    if args.apk:
        caps["app"] = args.apk
    else:
        caps["appPackage"] = args.app_package
        caps["appActivity"] = args.app_activity

    if args.app_wait_activity:
        caps["appWaitActivity"] = args.app_wait_activity

    return caps


def create_driver(appium_url: str, capabilities: dict[str, object]):
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as exc:
        fail("필수 패키지가 없습니다. 먼저 `pip install -r requirements.txt`를 실행하세요.")
        raise exc

    options = UiAutomator2Options().load_capabilities(capabilities)
    return webdriver.Remote(appium_url, options=options)


def main() -> int:
    args = parse_args()
    resolve_sdk_root(args.android_sdk_root)
    adb_path = resolve_executable(args.adb_path, "adb")

    appium_service = None
    driver = None

    try:
        serial = ensure_emulator(args, adb_path)
        appium_service = maybe_start_appium(args)
        caps = build_capabilities(args, serial)

        log("Appium 세션 생성 중...")
        driver = create_driver(args.appium_url, caps)

        current_package = getattr(driver, "current_package", None)
        if callable(current_package):
            current_package = current_package()
        log(f"앱 실행 완료. current_package={current_package or 'unknown'}")

        if args.launch_wait > 0:
            log(f"{args.launch_wait}초 동안 앱 상태 유지")
            time.sleep(args.launch_wait)

        return 0
    finally:
        if driver is not None:
            driver.quit()
            log("Appium 세션 종료")

        if appium_service is not None and not args.keep_appium_running:
            appium_service.stop()
            log("Python AppiumService로 시작한 서버 종료")


if __name__ == "__main__":
    raise SystemExit(main())
