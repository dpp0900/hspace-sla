from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from .console import fail, log
from .process import resolve_sdk_root

if TYPE_CHECKING:
    from .config import LaunchConfig


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


def maybe_start_appium(config: LaunchConfig):
    if is_appium_server_ready(config.appium_url):
        log(f"기존 Appium 서버 사용: {config.appium_url}")
        return None

    if not config.start_appium:
        fail(
            "Appium 서버에 연결할 수 없습니다. 먼저 Appium을 실행하거나 "
            "--start-appium 옵션을 사용하세요."
        )

    try:
        from appium.webdriver.appium_service import AppiumService, AppiumServiceError
    except ImportError:
        fail("필수 패키지가 없습니다. 먼저 `pip install -r requirements.txt`를 실행하세요.")

    service = AppiumService()
    host, port, base_path = parse_appium_url(config.appium_url)
    service_args = ["--address", host, "--port", str(port)]

    if base_path:
        service_args.extend(["--base-path", base_path])

    start_kwargs: dict[str, object] = {
        "args": service_args,
        "env": build_appium_env(resolve_sdk_root(config.android_sdk_root)),
        "timeout_ms": config.server_timeout * 1000,
    }
    if config.node_path:
        start_kwargs["node"] = config.node_path
    if config.npm_path:
        start_kwargs["npm"] = config.npm_path
    if config.appium_main_script:
        start_kwargs["main_script"] = config.appium_main_script

    log(f"Python AppiumService로 서버 시작: {config.appium_url}")
    try:
        service.start(**start_kwargs)
    except (AppiumServiceError, FileNotFoundError) as exc:
        fail(
            "Python AppiumService로 서버 시작에 실패했습니다. "
            "Appium 서버 패키지와 드라이버가 설치되어 있는지 확인하세요.\n"
            f"원인: {exc}"
        )
    wait_for_appium(config.appium_url, config.server_timeout)
    return service
