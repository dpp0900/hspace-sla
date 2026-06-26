from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from sla_app.adapters.android_appium import AndroidAppiumAdapter
from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.yaml_loader import SuiteValidationError, load_suite, suite_from_yaml_text, suite_to_yaml
from sla_app.storage import SqliteStore


TransportName = Literal["stdio", "sse", "streamable-http"]

MCP_INSTRUCTIONS = """
HSPACE SLA Runner MCP exposes Android Appium SLA suites and execution reports.
Use read-only tools first to inspect suites, YAML, recent runs, and failure reasons.
Only call write or run tools when the server was started with the corresponding allow flag.
Suite execution can start an Android emulator, Appium, and an APK install/session.
""".strip()


class SlaMcpService:
    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        allow_writes: bool | None = None,
        allow_runs: bool | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or os.getenv("SLA_APP_HOME", ".")).resolve()
        self.store = SqliteStore(self.base_dir)
        self.allow_writes = _env_bool("SLA_MCP_ALLOW_WRITES", default=False) if allow_writes is None else allow_writes
        self.allow_runs = _env_bool("SLA_MCP_ALLOW_RUNS", default=False) if allow_runs is None else allow_runs

    def sync_suite_files(self) -> dict[str, object]:
        imported = []
        skipped = []
        for path in sorted(self.store.suites_dir.glob("*.yaml")):
            try:
                suite = load_suite(path)
                self.store.register_suite_file(path.stem, suite, path)
                imported.append({"suite_id": path.stem, "path": str(path), "name": suite.name})
            except Exception as exc:  # noqa: BLE001 - MCP should report bad local suite files.
                skipped.append({"path": str(path), "error": str(exc)})
        return {"imported": imported, "skipped": skipped}

    def list_suites(self) -> dict[str, object]:
        self.sync_suite_files()
        suites = []
        for summary in self.store.list_suites():
            try:
                suite = self.store.load_suite(summary.suite_id)
                suites.append(
                    {
                        "suite_id": summary.suite_id,
                        "name": summary.name,
                        "yaml_path": str(summary.yaml_path),
                        "updated_at": summary.updated_at,
                        "app": suite.app.to_dict(),
                        "scenario_count": len(suite.scenarios),
                        "step_count": sum(len(scenario.steps) for scenario in suite.scenarios),
                        "thresholds": suite.thresholds.to_dict(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - keep listing other suites.
                suites.append(
                    {
                        "suite_id": summary.suite_id,
                        "name": summary.name,
                        "yaml_path": str(summary.yaml_path),
                        "updated_at": summary.updated_at,
                        "error": str(exc),
                    }
                )
        return {
            "base_dir": str(self.base_dir),
            "db_path": str(self.store.db_path),
            "count": len(suites),
            "suites": suites,
        }

    def get_suite(self, suite_id: str, *, include_yaml: bool = True) -> dict[str, object]:
        self.sync_suite_files()
        suite = self.store.load_suite(suite_id)
        summary = self.store.get_suite_summary(suite_id)
        data: dict[str, object] = {
            "suite_id": suite_id,
            "name": suite.name,
            "yaml_path": str(summary.yaml_path) if summary else str(suite.source_path or ""),
            "app": suite.app.to_dict(),
            "thresholds": suite.thresholds.to_dict(),
            "scenarios": [
                {
                    "name": scenario.name,
                    "step_count": len(scenario.steps),
                    "actions": [step.action for step in scenario.steps],
                    "thresholds": scenario.thresholds.to_dict() if scenario.thresholds else None,
                }
                for scenario in suite.scenarios
            ],
        }
        if include_yaml:
            data["yaml"] = self.store.get_suite_yaml(suite_id)
        return data

    def validate_suite_yaml(self, yaml_text: str) -> dict[str, object]:
        try:
            suite = suite_from_yaml_text(yaml_text)
        except SuiteValidationError as exc:
            return {"valid": False, "error": str(exc)}
        return {
            "valid": True,
            "suite": {
                "name": suite.name,
                "app": suite.app.to_dict(),
                "thresholds": suite.thresholds.to_dict(),
                "scenario_count": len(suite.scenarios),
                "step_count": sum(len(scenario.steps) for scenario in suite.scenarios),
            },
            "normalized_yaml": suite_to_yaml(suite),
        }

    def save_suite_yaml(self, yaml_text: str, suite_id: str | None = None) -> dict[str, object]:
        if not self.allow_writes:
            return {
                "ok": False,
                "error": "write tools are disabled; start MCP with --allow-writes or SLA_MCP_ALLOW_WRITES=true",
            }
        suite = suite_from_yaml_text(yaml_text)
        if suite_id:
            normalized_suite_id = _normalize_suite_id(suite_id)
            yaml_path = self.store.suites_dir / f"{normalized_suite_id}.yaml"
            yaml_path.write_text(yaml_text, encoding="utf-8")
            summary = self.store.register_suite_file(normalized_suite_id, suite, yaml_path)
        else:
            summary = self.store.save_suite(suite, yaml_text)
        return {
            "ok": True,
            "suite_id": summary.suite_id,
            "name": summary.name,
            "yaml_path": str(summary.yaml_path),
        }

    def list_runs(self, suite_id: str | None = None, limit: int = 20) -> dict[str, object]:
        safe_limit = max(1, min(int(limit), 100))
        runs = (
            self.store.list_runs_for_suite(suite_id, limit=safe_limit)
            if suite_id
            else self.store.list_runs(limit=safe_limit)
        )
        return {
            "suite_id": suite_id,
            "limit": safe_limit,
            "count": len(runs),
            "runs": [
                {
                    "run_id": run.run_id,
                    "suite_id": run.suite_id,
                    "suite_name": run.suite_name,
                    "status": run.status,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "duration_ms": run.duration_ms,
                    "assertion_failures": run.assertion_failures,
                    "metric_violations": run.metric_violations,
                    "reasons": run.reasons,
                    "artifact_dir": run.artifact_dir,
                }
                for run in runs
            ],
        }

    def get_run_report(self, run_id: str) -> dict[str, object]:
        detail = self.store.get_run_detail(run_id)
        if detail is None:
            return {"ok": False, "error": f"run not found: {run_id}"}
        return {"ok": True, "run": detail}

    def database_status(self) -> dict[str, object]:
        return self.store.database_status()

    def run_suite(self, suite_id: str) -> dict[str, object]:
        if not self.allow_runs:
            return {
                "ok": False,
                "error": "run tools are disabled; start MCP with --allow-runs or SLA_MCP_ALLOW_RUNS=true",
            }
        self.sync_suite_files()
        suite = self.store.load_suite(suite_id)
        adapter = AndroidAppiumAdapter.from_suite(suite)
        run_id = uuid.uuid4().hex
        run = execute_suite(
            suite,
            adapter,
            suite_id=suite_id,
            options=ExecutionOptions(
                run_id=run_id,
                artifact_dir=self.store.artifact_dir_for_run(run_id),
            ),
        )
        self.store.save_run(run)
        return {"ok": True, "run": run.to_dict()}

    def inspect_suite_elements(self, suite_id: str, mode: str = "standard") -> dict[str, object]:
        if not self.allow_runs:
            return {
                "ok": False,
                "error": "device inspection is disabled; start MCP with --allow-runs or SLA_MCP_ALLOW_RUNS=true",
            }
        self.sync_suite_files()
        suite = self.store.load_suite(suite_id)
        adapter = AndroidAppiumAdapter.from_suite(suite)
        try:
            elements = adapter.inspect_elements(mode=mode)
        finally:
            adapter.close()
        return {"ok": True, "suite_id": suite_id, "mode": mode, "count": len(elements), "elements": elements}

    def read_doc(self, relative_path: str) -> dict[str, object]:
        path = (Path(__file__).resolve().parents[2] / relative_path).resolve()
        root = Path(__file__).resolve().parents[2]
        if root not in path.parents and path != root:
            return {"ok": False, "error": "document path escapes project root"}
        if not path.is_file():
            return {"ok": False, "error": f"document not found: {relative_path}"}
        return {"ok": True, "path": str(path), "text": path.read_text(encoding="utf-8")}


def create_mcp_server(
    *,
    service: SlaMcpService | None = None,
    host: str = "127.0.0.1",
    port: int = 8001,
    log_level: str | None = None,
) -> FastMCP:
    service = service or SlaMcpService()
    mcp = FastMCP(
        "HSPACE SLA Runner",
        instructions=MCP_INSTRUCTIONS,
        host=host,
        port=port,
        log_level=_mcp_log_level(log_level or os.getenv("SLA_MCP_LOG_LEVEL", "WARNING")),
        json_response=True,
    )

    @mcp.tool()
    def sync_suite_files() -> dict[str, object]:
        """Import local suites/*.yaml files into the SLA SQLite index."""
        return service.sync_suite_files()

    @mcp.tool()
    def list_suites() -> dict[str, object]:
        """List registered Android SLA suites with app targets, thresholds, and step counts."""
        return service.list_suites()

    @mcp.tool()
    def get_suite(suite_id: str, include_yaml: bool = True) -> dict[str, object]:
        """Get a suite summary and optionally its YAML source."""
        return service.get_suite(suite_id, include_yaml=include_yaml)

    @mcp.tool()
    def validate_suite_yaml(yaml_text: str) -> dict[str, object]:
        """Validate SLA suite YAML and return normalized YAML when valid."""
        return service.validate_suite_yaml(yaml_text)

    @mcp.tool()
    def save_suite_yaml(yaml_text: str, suite_id: str | None = None) -> dict[str, object]:
        """Save a suite YAML file. Requires --allow-writes or SLA_MCP_ALLOW_WRITES=true."""
        return service.save_suite_yaml(yaml_text, suite_id=suite_id)

    @mcp.tool()
    def list_runs(suite_id: str | None = None, limit: int = 20) -> dict[str, object]:
        """List recent SLA runs, optionally scoped to one suite."""
        return service.list_runs(suite_id=suite_id, limit=limit)

    @mcp.tool()
    def get_run_report(run_id: str) -> dict[str, object]:
        """Return the full JSON detail for a completed or failed SLA run."""
        return service.get_run_report(run_id)

    @mcp.tool()
    def database_status() -> dict[str, object]:
        """Return SQLite health and count information used by readiness checks."""
        return service.database_status()

    @mcp.tool()
    def run_suite(suite_id: str) -> dict[str, object]:
        """Execute an Android SLA suite via Appium. Requires --allow-runs or SLA_MCP_ALLOW_RUNS=true."""
        return service.run_suite(suite_id)

    @mcp.tool()
    def inspect_suite_elements(suite_id: str, mode: str = "standard") -> dict[str, object]:
        """Launch the suite app and return visible UI element candidates. Requires run permission."""
        return service.inspect_suite_elements(suite_id, mode=mode)

    @mcp.resource("sla://suites")
    def suites_resource() -> str:
        """JSON list of registered suites."""
        return _json_text(service.list_suites())

    @mcp.resource("sla://suites/{suite_id}")
    def suite_resource(suite_id: str) -> str:
        """JSON suite summary plus YAML for one suite."""
        return _json_text(service.get_suite(suite_id, include_yaml=True))

    @mcp.resource("sla://runs/recent")
    def recent_runs_resource() -> str:
        """JSON list of recent SLA runs."""
        return _json_text(service.list_runs(limit=20))

    @mcp.resource("sla://runs/{run_id}")
    def run_resource(run_id: str) -> str:
        """JSON run report for one run."""
        return _json_text(service.get_run_report(run_id))

    @mcp.resource("sla://docs/yaml-guide")
    def yaml_guide_resource() -> str:
        """Markdown SLA YAML guide."""
        return service.read_doc("docs/yaml-guide.md").get("text", "")

    @mcp.resource("sla://docs/mcp")
    def mcp_doc_resource() -> str:
        """Markdown MCP integration guide."""
        return service.read_doc("docs/mcp.md").get("text", "")

    @mcp.prompt()
    def draft_android_sla_suite(app_goal: str, package_or_apk: str = "test-apk/build/hspace-test-app-debug.apk") -> str:
        """Prompt template for drafting an Android SLA suite YAML."""
        return (
            "Draft a valid HSPACE SLA Runner YAML suite for this Android app goal:\n"
            f"{app_goal}\n\n"
            f"Target package/APK hint: {package_or_apk}\n"
            "Use stable accessibility_id or resource-id selectors, include functional assertions, "
            "a screenshot step, collect_metrics, and metric_check thresholds. "
            "Validate the final YAML with validate_suite_yaml before saving."
        )

    @mcp.prompt()
    def analyze_failed_run(run_id: str) -> str:
        """Prompt template for analyzing one failed SLA run."""
        return (
            f"Use get_run_report(run_id={run_id!r}) and explain the failure in Korean. "
            "Prioritize failed step index/action, failure_category, assertion or metric violation, "
            "likely root cause, and the smallest suite/app/environment fix."
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.base_dir:
        os.environ["SLA_APP_HOME"] = str(Path(args.base_dir).resolve())
    if args.db_path:
        os.environ["SLA_DB_PATH"] = str(Path(args.db_path).resolve())
    if args.allow_writes:
        os.environ["SLA_MCP_ALLOW_WRITES"] = "true"
    if args.allow_runs:
        os.environ["SLA_MCP_ALLOW_RUNS"] = "true"

    service = SlaMcpService(
        base_dir=args.base_dir,
        allow_writes=args.allow_writes or None,
        allow_runs=args.allow_runs or None,
    )
    service.sync_suite_files()
    mcp = create_mcp_server(service=service, host=args.host, port=args.port, log_level=args.log_level)
    mcp.run(transport=args.transport, mount_path=args.mount_path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the HSPACE SLA Runner MCP server.")
    parser.add_argument("--transport", choices=("stdio", "sse", "streamable-http"), default=os.getenv("SLA_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.getenv("SLA_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SLA_MCP_PORT", "8001")))
    parser.add_argument("--log-level", default=os.getenv("SLA_MCP_LOG_LEVEL", "WARNING"))
    parser.add_argument("--mount-path", default=os.getenv("SLA_MCP_MOUNT_PATH") or None)
    parser.add_argument("--base-dir", default=os.getenv("SLA_APP_HOME"))
    parser.add_argument("--db-path", default=os.getenv("SLA_DB_PATH"))
    parser.add_argument("--allow-writes", action="store_true", default=_env_bool("SLA_MCP_ALLOW_WRITES", default=False))
    parser.add_argument("--allow-runs", action="store_true", default=_env_bool("SLA_MCP_ALLOW_RUNS", default=False))
    return parser.parse_args(argv)


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _mcp_log_level(value: str) -> Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    normalized = value.strip().upper()
    if normalized in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return normalized  # type: ignore[return-value]
    return "WARNING"


def _normalize_suite_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    if not normalized:
        raise ValueError("suite_id must contain at least one letter, number, underscore, or hyphen")
    return normalized


if __name__ == "__main__":
    main()
