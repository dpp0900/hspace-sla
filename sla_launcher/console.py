from __future__ import annotations

import sys
from typing import NoReturn


def log(message: str) -> None:
    print(f"[INFO] {message}")


def fail(message: str, exit_code: int = 1) -> NoReturn:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(exit_code)
