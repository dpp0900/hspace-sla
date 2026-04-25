from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .console import fail, log
from .paths import platform_executable_name, sdk_tool_path
from .process import resolve_executable, run_command, spawn_background_process

if TYPE_CHECKING:
    from .config import LaunchConfig


@dataclass(frozen=True)
class AvdDefinition:
    name: str
    path: Path
    abi: str
    cpu_arch: str
    system_image: str


def detect_host_architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    return machine


def avd_home() -> Path:
    return Path(os.getenv("ANDROID_AVD_HOME", Path.home() / ".android" / "avd")).expanduser()


def parse_ini_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def normalize_abi(value: str) -> str:
    normalized = value.strip().lower()
    if "arm64-v8a" in normalized or normalized == "arm64":
        return "arm64-v8a"
    if "x86_64" in normalized:
        return "x86_64"
    if normalized == "x86":
        return "x86"
    return normalized


def load_avd_definitions() -> list[AvdDefinition]:
    definitions: list[AvdDefinition] = []
    home = avd_home()
    for ini_path in sorted(home.glob("*.ini")):
        ini_data = parse_ini_file(ini_path)
        config_dir = Path(ini_data.get("path", home / f"{ini_path.stem}.avd")).expanduser()
        config_path = config_dir / "config.ini"
        config_data = parse_ini_file(config_path) if config_path.exists() else {}
        definitions.append(
            AvdDefinition(
                name=ini_path.stem,
                path=config_dir,
                abi=normalize_abi(config_data.get("abi.type", "")),
                cpu_arch=config_data.get("hw.cpu.arch", "").strip().lower(),
                system_image=config_data.get("image.sysdir.1", "").strip(),
            )
        )
    return definitions


def preferred_abis_for_host(host_arch: str) -> list[str]:
    if host_arch == "arm64":
        return ["arm64-v8a"]
    if host_arch == "x86_64":
        return ["x86_64", "x86"]
    return [host_arch]


def avd_supported_abis(definition: AvdDefinition) -> set[str]:
    candidates = {
        normalize_abi(definition.abi),
        normalize_abi(definition.cpu_arch),
        normalize_abi(Path(definition.system_image.rstrip("/")).name),
    }
    return {candidate for candidate in candidates if candidate}


def avd_label(definition: AvdDefinition) -> str:
    supported = sorted(avd_supported_abis(definition))
    abi_label = "/".join(supported) if supported else "unknown"
    return f"{definition.name}[{abi_label}]"


def select_compatible_avd(explicit_avd: str | None) -> str:
    definitions = load_avd_definitions()
    if not definitions:
        fail(
            "Android AVD를 찾지 못했습니다. Android Studio Device Manager 또는 avdmanager로 "
            "에뮬레이터를 먼저 생성하세요."
        )

    if explicit_avd:
        if any(definition.name == explicit_avd for definition in definitions):
            return explicit_avd
        available = ", ".join(avd_label(definition) for definition in definitions)
        fail(f"지정한 AVD를 찾지 못했습니다: {explicit_avd}. available={available}")

    host_arch = detect_host_architecture()
    preferred_abis = preferred_abis_for_host(host_arch)
    for preferred_abi in preferred_abis:
        for definition in definitions:
            if preferred_abi in avd_supported_abis(definition):
                log(f"호스트 아키텍처({host_arch})에 맞는 AVD 자동 선택: {avd_label(definition)}")
                return definition.name

    available = ", ".join(avd_label(definition) for definition in definitions)
    fail(
        "호스트 아키텍처에 맞는 AVD를 찾지 못했습니다. "
        f"host={host_arch}, required ABI={', '.join(preferred_abis)}, available={available}. "
        "README의 환경 구성 가이드를 참고해 적절한 system image로 AVD를 생성하거나 "
        "--avd / ANDROID_AVD로 직접 지정하세요."
    )


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
                run_command([adb_path, "-s", serial, "shell", "input", "keyevent", "82"], check=False)
                log(f"{serial} 부팅 완료")
                return
        except subprocess.SubprocessError:
            pass
        time.sleep(3)

    fail(f"{serial} 부팅이 {timeout}초 안에 완료되지 않았습니다.")


def ensure_emulator(config: LaunchConfig, adb_path: str) -> str:
    if config.serial:
        if config.serial not in adb_devices(adb_path):
            fail(f"지정한 시리얼이 연결되어 있지 않습니다: {config.serial}")
        wait_for_boot(adb_path, config.serial, config.boot_timeout)
        return config.serial

    running = emulator_devices(adb_path)
    if running:
        serial = running[0]
        log(f"이미 실행 중인 에뮬레이터 사용: {serial}")
        wait_for_boot(adb_path, serial, config.boot_timeout)
        return serial

    emulator_hint = config.emulator_path or sdk_tool_path(
        config.android_sdk_root,
        "emulator",
        platform_executable_name("emulator"),
    )
    emulator_path = resolve_executable(emulator_hint, platform_executable_name("emulator"))
    selected_avd = select_compatible_avd(config.avd)
    launch_command = [emulator_path, f"@{selected_avd}", *config.emulator_args]

    log(f"AVD 실행: {selected_avd}")
    spawn_background_process(launch_command)

    serial = wait_for_new_emulator(adb_path, set(running), config.boot_timeout)
    wait_for_boot(adb_path, serial, config.boot_timeout)
    return serial
