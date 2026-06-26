from __future__ import annotations

import asyncio
from pathlib import Path

from sla_app.core.models import RunRecord
from sla_app.mcp.server import SlaMcpService, create_mcp_server


VALID_YAML = """name: MCP Demo
app:
  platform: android
  apk: app.apk
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
scenarios:
  - name: smoke
    steps:
      - action: launch_app
      - action: assert_text
        text: Ready
"""


def test_mcp_service_syncs_and_reads_suite_files(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "mcp_demo.yaml").write_text(VALID_YAML, encoding="utf-8")

    service = SlaMcpService(base_dir=tmp_path, allow_writes=False, allow_runs=False)

    sync_result = service.sync_suite_files()
    suite_list = service.list_suites()
    suite_detail = service.get_suite("mcp_demo")

    assert sync_result["skipped"] == []
    assert suite_list["count"] == 1
    assert suite_list["suites"][0]["suite_id"] == "mcp_demo"
    assert suite_detail["name"] == "MCP Demo"
    assert "launch_app" in suite_detail["yaml"]


def test_mcp_service_validates_and_saves_yaml_when_enabled(tmp_path: Path) -> None:
    service = SlaMcpService(base_dir=tmp_path, allow_writes=True, allow_runs=False)

    validation = service.validate_suite_yaml(VALID_YAML)
    saved = service.save_suite_yaml(VALID_YAML, suite_id="demo_suite")

    assert validation["valid"] is True
    assert saved["ok"] is True
    assert saved["suite_id"] == "demo_suite"
    assert (tmp_path / "suites" / "demo_suite.yaml").exists()


def test_mcp_service_blocks_writes_and_runs_by_default(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "mcp_demo.yaml").write_text(VALID_YAML, encoding="utf-8")
    service = SlaMcpService(base_dir=tmp_path, allow_writes=False, allow_runs=False)

    write_result = service.save_suite_yaml(VALID_YAML, suite_id="blocked")
    run_result = service.run_suite("mcp_demo")

    assert write_result["ok"] is False
    assert "disabled" in write_result["error"]
    assert run_result["ok"] is False
    assert "disabled" in run_result["error"]


def test_mcp_service_lists_and_reads_run_reports(tmp_path: Path) -> None:
    service = SlaMcpService(base_dir=tmp_path, allow_writes=False, allow_runs=False)
    run = RunRecord(
        run_id="run-1",
        suite_id="mcp_demo",
        suite_name="MCP Demo",
        status="PASS",
        started_at="2026-06-26T00:00:00+00:00",
        ended_at="2026-06-26T00:00:01+00:00",
        duration_ms=1000,
        assertion_failures=0,
        metric_violations=0,
        reasons=[],
        artifact_dir=str(tmp_path / "artifacts" / "run-1"),
    )

    service.store.save_run(run)
    runs = service.list_runs(limit=5)
    report = service.get_run_report("run-1")

    assert runs["count"] == 1
    assert runs["runs"][0]["run_id"] == "run-1"
    assert report["ok"] is True
    assert report["run"]["status"] == "PASS"


def test_fastmcp_server_registers_expected_tools(tmp_path: Path) -> None:
    service = SlaMcpService(base_dir=tmp_path, allow_writes=False, allow_runs=False)
    mcp = create_mcp_server(service=service)

    tools = asyncio.run(mcp.list_tools())
    tool_names = {tool.name for tool in tools}

    assert "list_suites" in tool_names
    assert "get_suite" in tool_names
    assert "validate_suite_yaml" in tool_names
    assert "run_suite" in tool_names
    assert "inspect_suite_elements" in tool_names
