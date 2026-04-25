from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from .console import fail


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


def resolve_executable(path_hint: str | None, command_name: str) -> str:
    expanded = str(Path(path_hint).expanduser()) if path_hint else ""
    if expanded and Path(expanded).exists():
        return expanded

    found = shutil.which(command_name)
    if found:
        return found

    candidate = expanded or command_name
    fail(f"{command_name} 실행 파일을 찾지 못했습니다. 경로를 확인하세요: {candidate}")


def resolve_sdk_root(path_hint: str) -> str:
    expanded = str(Path(path_hint).expanduser())
    if Path(expanded).exists():
        return expanded
    fail(f"Android SDK 경로를 찾지 못했습니다: {expanded}")


def spawn_background_process(command: Sequence[str]) -> subprocess.Popen[bytes]:
    popen_kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        if creationflags:
            popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(list(command), **popen_kwargs)
