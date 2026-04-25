from __future__ import annotations

import os
import platform
from pathlib import Path


def default_sdk_root() -> Path:
    system = platform.system().lower()
    home = Path.home()
    if system == "darwin":
        return home / "Library" / "Android" / "sdk"
    if system == "windows":
        return home / "AppData" / "Local" / "Android" / "Sdk"
    return home / "Android" / "Sdk"


def platform_executable_name(command_name: str) -> str:
    if os.name == "nt" and not command_name.endswith(".exe"):
        return f"{command_name}.exe"
    return command_name


def sdk_tool_path(sdk_root: str | Path, *relative_parts: str) -> str:
    return str(Path(sdk_root).expanduser() / Path(*relative_parts))
