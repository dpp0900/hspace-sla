from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import uvicorn

_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}
_UVICORN_LOG_LEVELS = {
    "CRITICAL": "critical",
    "ERROR": "error",
    "WARNING": "warning",
    "WARN": "warning",
    "INFO": "info",
    "DEBUG": "debug",
}


def main() -> None:
    _configure_logging()
    uvicorn.run("sla_app.web.app:create_app", factory=True, **_server_options_from_env())


def _configure_logging(env: Mapping[str, str] | None = None) -> None:
    logging.basicConfig(
        level=_log_level_from_env(env),
        format="%(levelname)s:%(name)s:%(message)s",
    )


def _server_options_from_env(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    options: dict[str, Any] = {
        "host": values.get("SLA_WEB_HOST", "127.0.0.1"),
        "port": _env_int(values, "SLA_WEB_PORT", 8000),
        "proxy_headers": _env_bool(values, "SLA_PROXY_HEADERS", default=True),
        "forwarded_allow_ips": values.get("SLA_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        "root_path": values.get("SLA_ROOT_PATH", ""),
        "log_level": _uvicorn_log_level_from_env(values),
    }
    graceful_timeout = _env_optional_int(values, "SLA_GRACEFUL_SHUTDOWN_TIMEOUT")
    if graceful_timeout is not None:
        options["timeout_graceful_shutdown"] = graceful_timeout
    return options


def _log_level_from_env(env: Mapping[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    return _LOG_LEVELS.get(_log_level_name(values), logging.INFO)


def _uvicorn_log_level_from_env(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    return _UVICORN_LOG_LEVELS.get(_log_level_name(values), "info")


def _log_level_name(env: Mapping[str, str]) -> str:
    return (env.get("SLA_LOG_LEVEL") or "INFO").strip().upper()


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_optional_int(env: Mapping[str, str], name: str) -> int | None:
    value = env.get(name)
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


if __name__ == "__main__":
    main()
