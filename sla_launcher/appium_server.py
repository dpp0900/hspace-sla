from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
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
        str(Path.home() / "node_modules" / ".bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
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
    service_args = [
        "--address",
        host,
        "--port",
        str(port),
        "--allow-insecure",
        "uiautomator2:adb_shell",
    ]

    if base_path:
        service_args.extend(["--base-path", base_path])

    node_path = _discover_executable(config.node_path, "node")
    npm_path = _discover_executable(config.npm_path, "npm")
    main_script = _discover_appium_main_script(config.appium_main_script, npm_path)

    start_kwargs: dict[str, object] = {
        "args": service_args,
        "env": build_appium_env(resolve_sdk_root(config.android_sdk_root)),
        "timeout_ms": config.server_timeout * 1000,
    }
    if node_path:
        start_kwargs["node"] = node_path
    if npm_path:
        start_kwargs["npm"] = npm_path
    if main_script:
        start_kwargs["main_script"] = main_script

    log(f"Python AppiumService로 서버 시작: {config.appium_url}")
    try:
        service.start(**start_kwargs)
    except (AppiumServiceError, FileNotFoundError) as exc:
        fail(
            "Python AppiumService로 서버 시작에 실패했습니다. "
            "Appium 서버 패키지와 드라이버가 설치되어 있는지 확인하세요.\n"
            f"원인: {_format_appium_start_error(exc)}"
        )
    wait_for_appium(config.appium_url, config.server_timeout)
    return service


def _discover_executable(configured_path: str | None, executable_name: str) -> str | None:
    candidates = [
        configured_path,
        shutil.which(executable_name),
        f"/opt/homebrew/bin/{executable_name}",
        f"/usr/local/bin/{executable_name}",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return configured_path


def _discover_appium_main_script(configured_path: str | None, npm_path: str | None) -> str | None:
    if configured_path:
        return _normalize_appium_main_script(Path(configured_path).expanduser())

    for candidate in _appium_main_script_candidates(npm_path):
        if candidate.exists():
            return _normalize_appium_main_script(candidate)
    return None


def _appium_main_script_candidates(npm_path: str | None) -> list[Path]:
    candidates: list[Path] = []
    for modules_root in _npm_module_roots(npm_path):
        candidates.append(modules_root / "appium" / "build" / "lib" / "main.js")
        candidates.append(modules_root / "appium" / "index.js")

    home_modules = Path.home() / "node_modules" / "appium"
    candidates.extend(
        [
            home_modules / "build" / "lib" / "main.js",
            home_modules / "index.js",
        ]
    )
    return _dedupe_paths(candidates)


def _npm_module_roots(npm_path: str | None) -> list[Path]:
    npm = npm_path or shutil.which("npm")
    if not npm:
        return []

    roots: list[Path] = []
    for args in (("root",), ("root", "-g")):
        try:
            output = sp.check_output([npm, *args], stderr=sp.DEVNULL, text=True).strip()
        except (OSError, sp.CalledProcessError):
            continue
        if output:
            roots.append(Path(output))
    return _dedupe_paths(roots)


def _normalize_appium_main_script(path: Path) -> str:
    resolved = path.resolve()
    if resolved.name == "appium.js":
        main_script = resolved.with_name("main.js")
        if main_script.exists():
            return str(main_script)
    return str(resolved)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _format_appium_start_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message and message != "b''":
        return message
    return (
        "Appium 실행 로그가 비어 있습니다. node/npm 또는 Appium main.js를 찾지 못했을 수 있습니다. "
        "로컬 설치는 ~/node_modules/appium/build/lib/main.js까지 자동 탐색합니다."
    )
