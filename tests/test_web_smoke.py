from __future__ import annotations

import base64
import io
import tempfile
import threading
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from sla_app.core.models import RunRecord, ScenarioResult, SlaVerdict, StepResult
from sla_app.core.yaml_loader import suite_from_yaml_text


VALID_YAML = """name: Web Suite
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: launch_app
"""


class WebSmokeTests(unittest.TestCase):
    def test_core_pages_respond(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                },
            ),
        ):
            try:
                app = create_app(tmp)
            except RuntimeError as exc:
                if "python-multipart" in str(exc):
                    self.skipTest("python-multipart is not installed")
                raise

            store = app.state.store
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)
            store.save_run(
                RunRecord(
                    run_id="run-old",
                    suite_id=summary.suite_id,
                    suite_name=suite.name,
                    status="FAIL",
                    started_at="2026-04-22T00:00:00+00:00",
                    ended_at="2026-04-22T00:00:01+00:00",
                    duration_ms=1300,
                    assertion_failures=0,
                    metric_violations=0,
                    reasons=["scenario execution failed"],
                    artifact_dir=str(store.artifact_dir_for_run("run-old")),
                    scenarios=[
                        ScenarioResult(
                            name="smoke",
                            success=False,
                            duration_ms=1300,
                            step_results=[
                                StepResult(
                                    index=1,
                                    action="launch_app",
                                    success=False,
                                    duration_ms=1300,
                                    message="launcher exited with code 1",
                                    failure_category="환경/실행",
                                )
                            ],
                            assertion_count=0,
                            assertion_failures=0,
                            metric_violations=0,
                            metrics={"memory_mb": 72, "launch_time_ms": 1200},
                            verdict=SlaVerdict(status="FAIL", reasons=["scenario execution failed"]),
                        )
                    ],
                )
            )
            store.save_run(
                RunRecord(
                    run_id="run-web",
                    suite_id=summary.suite_id,
                    suite_name=suite.name,
                    status="PASS",
                    started_at="2026-04-23T00:00:00+00:00",
                    ended_at="2026-04-23T00:00:01+00:00",
                    duration_ms=1000,
                    assertion_failures=0,
                    metric_violations=0,
                    reasons=[],
                    artifact_dir=str(store.artifact_dir_for_run("run-web")),
                    scenarios=[
                        ScenarioResult(
                            name="smoke",
                            success=True,
                            duration_ms=1000,
                            step_results=[
                                StepResult(
                                    index=1,
                                    action="collect_metrics",
                                    success=True,
                                    duration_ms=50,
                                    metrics={
                                        "memory_mb": 80,
                                        "launch_time_ms": 900,
                                        "cpu_percent": 12.5,
                                    },
                                    screenshot_path=str(
                                        store.artifact_dir_for_run("run-web") / "screen.png"
                                    ),
                                )
                            ],
                            assertion_count=0,
                            assertion_failures=0,
                            metric_violations=0,
                            metrics={
                                "memory_mb": 80,
                                "launch_time_ms": 900,
                                "appium_command_max_ms": 42,
                                "cpu_percent": 12.5,
                            },
                            verdict=SlaVerdict(status="PASS", reasons=[]),
                        )
                    ],
                )
            )

            client = TestClient(app)
            for path in (
                "/",
                "/suites",
                f"/suites/{summary.suite_id}",
                "/suites/builder",
                f"/suites/{summary.suite_id}/edit",
                f"/suites/{summary.suite_id}/edit/helper",
                f"/suites/{summary.suite_id}/edit/yaml",
                "/runs/run-web",
                "/guide",
                "/settings",
            ):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)

            response = client.get("/")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["x-frame-options"], "DENY")
            self.assertEqual(response.headers["referrer-policy"], "same-origin")
            self.assertEqual(response.headers["cross-origin-opener-policy"], "same-origin")
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
            self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")

            response = client.get("/version", headers={"X-Request-ID": "runbook-123"})
            self.assertEqual(response.headers["x-request-id"], "runbook-123")

            with self.assertLogs("sla_app.web.app", level="INFO") as logs:
                response = client.get("/version", headers={"X-Request-ID": "runbook-log"})
            self.assertEqual(response.status_code, 200)
            log_line = "\n".join(logs.output)
            self.assertIn("request_id=runbook-log", log_line)
            self.assertIn("method=GET", log_line)
            self.assertIn("path=/version", log_line)
            self.assertIn("status=200", log_line)

            response = client.get("/version", headers={"X-Request-ID": "bad request id"})
            self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")
            self.assertNotEqual(response.headers["x-request-id"], "bad request id")

            response = client.get("/healthz")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(response.json()["version"], "0.1.0")

            response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            readyz = response.json()
            self.assertEqual(readyz["status"], "ok")
            database_check = next(check for check in readyz["checks"] if check["name"] == "database")
            self.assertIn("schema=1", database_check["detail"])
            self.assertIn("journal=wal", database_check["detail"])
            self.assertIn("quick_check=ok", database_check["detail"])

            response = client.get("/version")
            self.assertEqual(response.status_code, 200)
            version_payload = response.json()
            self.assertEqual(version_payload["service"], "sla-test-runner")
            self.assertEqual(version_payload["version"], "0.1.0")
            self.assertEqual(version_payload["runtime"]["auth_enabled"], False)
            self.assertEqual(version_payload["runtime"]["run_queue"]["queue_limit"], 10)
            self.assertEqual(version_payload["runtime"]["run_queue"]["available"], 10)
            self.assertEqual(version_payload["runtime"]["run_queue"]["reserved"], 0)

            response = client.get("/metrics")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/plain", response.headers["content-type"])
            metrics = response.text
            self.assertIn("sla_info", metrics)
            self.assertIn("sla_suites_total 1", metrics)
            self.assertIn("sla_runs_total 2", metrics)
            self.assertIn('sla_runs_by_status_total{status="PASS"} 1', metrics)
            self.assertIn('sla_runs_by_status_total{status="FAIL"} 1', metrics)
            self.assertIn(
                'sla_http_requests_total{method="GET",path="/version",status="200"}',
                metrics,
            )
            self.assertIn(
                'sla_http_request_duration_seconds_count{method="GET",path="/version",status="200"}',
                metrics,
            )
            self.assertIn("sla_database_healthy 1", metrics)

            response = client.get("/runs/run-web/report.json")
            self.assertEqual(response.status_code, 200)
            report = response.json()
            self.assertEqual(report["report_version"], 1)
            self.assertEqual(report["run"]["run_id"], "run-web")
            self.assertEqual(report["insights"][0]["title"], "SLA 통과")
            self.assertEqual(report["metric_summary"][0]["name"], "launch_time_ms")
            self.assertEqual(report["artifacts"][0]["url"], "/artifacts/run-web/screen.png")
            self.assertIn("attachment", response.headers["content-disposition"])

            builder_page = client.get("/suites/builder").text
            self.assertIn('name="csrf_token"', builder_page)
            self.assertIn('name="csrf-token"', builder_page)
            self.assertIn("화면 요소", builder_page)
            self.assertIn("요소 검색", builder_page)
            self.assertIn('name="element_mode"', builder_page)
            self.assertIn('value="advanced"', builder_page)
            self.assertIn("data-pick-element", builder_page)
            self.assertIn("addStepFromElement", builder_page)
            self.assertIn("isInputElement", builder_page)
            self.assertIn("elementCategories", builder_page)
            self.assertIn("elementCategoryTabButton", builder_page)
            self.assertIn("element-category-tabs", builder_page)
            self.assertIn("바로 누를 요소", builder_page)
            self.assertIn("입력칸", builder_page)
            self.assertIn("화면 텍스트", builder_page)
            self.assertIn("recommendedElementAction", builder_page)
            self.assertIn("추천:", builder_page)
            self.assertIn("스와이프", builder_page)
            self.assertIn("스크롤", builder_page)
            self.assertIn("앱 종료", builder_page)
            self.assertIn("앱 활성화", builder_page)
            self.assertIn("백그라운드", builder_page)
            self.assertIn("텍스트 미노출 검증", builder_page)
            self.assertIn("요소 미존재 검증", builder_page)
            self.assertIn("현재 패키지 검증", builder_page)
            self.assertIn("현재 화면 검증", builder_page)
            self.assertIn("표시 검증", builder_page)
            self.assertIn("속성 검증", builder_page)
            self.assertIn('name="step_direction"', builder_page)
            self.assertIn('name="step_percent"', builder_page)
            self.assertIn('name="step_attribute"', builder_page)
            self.assertIn('name="step_package"', builder_page)
            self.assertIn('name="step_activity"', builder_page)
            self.assertIn('name="launch_time_ms_max"', builder_page)
            self.assertIn('name="appium_new_session_ms_max"', builder_page)
            self.assertIn('name="appium_command_max_ms_max"', builder_page)
            self.assertIn('name="appium_command_avg_ms_max"', builder_page)
            self.assertIn('name="cpu_percent_max"', builder_page)
            self.assertIn('name="logcat_error_count_max"', builder_page)

            suites_page = client.get("/suites").text
            self.assertIn(f'href="/suites/{summary.suite_id}"', suites_page)
            self.assertIn("상세", suites_page)

            suite_page = client.get(f"/suites/{summary.suite_id}").text
            self.assertIn("스위트 운영", suite_page)
            self.assertIn("최근 20회 통과율", suite_page)
            self.assertIn("최근 수집 지표", suite_page)
            self.assertIn("최근 실행 흐름", suite_page)
            self.assertIn("실행 지연", suite_page)
            self.assertIn("300 ms 감소", suite_page)

            run_page = client.get("/runs/run-web").text
            self.assertIn("실행 분석", run_page)
            self.assertIn("SLA 통과", run_page)
            self.assertIn("이전 실행 대비", run_page)
            self.assertIn("수집 지표", run_page)
            self.assertIn("최근 실행 흐름", run_page)
            self.assertIn("실행 지연", run_page)
            self.assertIn("메모리", run_page)
            self.assertIn("300 ms 감소", run_page)
            self.assertIn("JSON 보고서", run_page)

            dashboard_page = client.get("/").text
            self.assertIn("최근 10회 통과율", dashboard_page)
            self.assertIn("최근 실패", dashboard_page)
            self.assertIn("가장 느린 실행", dashboard_page)

            settings_page = client.get("/settings").text
            self.assertIn("운영 데이터", settings_page)
            self.assertIn("백업 ZIP 다운로드", settings_page)
            self.assertIn("오래된 실행 정리", settings_page)

            response = client.get("/settings/backup.zip")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "application/zip")
            self.assertIn("attachment", response.headers["content-disposition"])
            with zipfile.ZipFile(io.BytesIO(response.content)) as backup:
                names = set(backup.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("database/sla_app.db", names)
            self.assertIn("suites/web-suite.yaml", names)

            with patch(
                "sla_app.web.app.collect_environment_diagnostics",
                return_value={
                    "host_arch": "arm64",
                    "summary": {"status": "ok", "ok": 9, "warn": 0, "fail": 0},
                    "checks": [{"key": "node", "title": "Node.js", "status": "ok", "message": "ok"}],
                },
            ):
                response = client.get("/settings/diagnostics")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["summary"]["status"], "ok")

            with patch(
                "sla_app.web.app._installed_apps_payload",
                return_value={
                    "device": "emulator-5554",
                    "apps": [
                        {
                            "label": "HSPACE Test App",
                            "package": "com.hspace.testapp",
                            "activity": ".MainActivity",
                            "app_wait_activity": "*",
                            "app_wait_package": "*",
                        }
                    ],
                },
            ):
                response = client.get("/android/installed-apps")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["apps"][0]["package"], "com.hspace.testapp")
            self.assertEqual(response.json()["apps"][0]["app_wait_activity"], "*")
            self.assertEqual(response.json()["apps"][0]["app_wait_package"], "*")

            class FakeAdapter:
                def inspect_elements(self, mode="standard"):
                    self.mode = mode
                    return [
                        {
                            "label": "Email",
                            "selector": "id=com.example:id/email",
                            "role": "input",
                            "confidence": "high",
                        }
                    ]

                def close(self) -> None:
                    pass

            fake_adapter = FakeAdapter()
            with patch("sla_app.web.app.AndroidAppiumAdapter.from_suite", return_value=fake_adapter):
                response = client.get(
                    "/android/elements",
                    params={"target_mode": "apk", "apk": "app.apk", "mode": "advanced"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["elements"][0]["selector"], "id=com.example:id/email")
            self.assertEqual(fake_adapter.mode, "advanced")

            captured_targets = []

            def fake_inspect_target(app_target, source_path=None, mode="standard"):
                captured_targets.append((app_target, mode))
                return {"elements": []}

            with patch("sla_app.web.app._inspect_app_target_elements", side_effect=fake_inspect_target):
                response = client.get(
                    "/android/elements",
                    params={
                        "target_mode": "installed",
                        "app_package": "com.google.android.calendar",
                        "app_activity": "com.android.calendar.AllInOneActivity",
                        "app_wait_activity": "com.android.calendar.AllInOneActivity",
                        "app_wait_package": "com.google.android.calendar",
                    },
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured_targets[0][0].app_wait_activity, "*")
            self.assertEqual(captured_targets[0][0].app_wait_package, "*")
            self.assertEqual(captured_targets[0][1], "standard")

            response = client.post(
                f"/suites/{summary.suite_id}/edit/helper",
                data=_with_csrf(
                    app,
                    {
                    "suite_name": "Edited Web Suite",
                    "target_mode": "apk",
                    "apk": "edited.apk",
                    "max_duration_ms": "25000",
                    "max_assertion_failures": "0",
                    "max_metric_violations": "0",
                    "required_assertions": "0",
                    "scenario_name": "edited smoke",
                    "step_action": ["launch_app", "wait"],
                    "step_selector": ["", ""],
                    "step_text": ["", ""],
                    "step_value": ["", ""],
                    "step_timeout_ms": ["", "500"],
                    "step_name": ["", ""],
                    "step_metric": ["", ""],
                    "step_min": ["", ""],
                    "step_max": ["", ""],
                    },
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            edited_suite = store.load_suite(summary.suite_id)
            self.assertEqual(edited_suite.name, "Edited Web Suite")
            self.assertEqual(edited_suite.app.apk, "edited.apk")
            self.assertEqual(edited_suite.scenarios[0].steps[1].timeout_ms, 500)

            with patch("sla_app.web.app.AndroidAppiumAdapter.from_suite", return_value=FakeAdapter()):
                response = client.get(f"/suites/{summary.suite_id}/elements")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["elements"][0]["selector"], "id=com.example:id/email")

            response = client.post(
                "/suites/builder",
                data=_with_csrf(
                    app,
                    {
                    "suite_name": "Builder Suite",
                    "target_mode": "apk",
                    "apk": "app.apk",
                    "max_duration_ms": "30000",
                    "max_assertion_failures": "0",
                    "max_metric_violations": "0",
                    "launch_time_ms_max": "5000",
                    "appium_command_max_ms_max": "500",
                    "cpu_percent_max": "80",
                    "logcat_error_count_max": "0",
                    "scenario_name": "builder smoke",
                    "step_action": ["launch_app", "wait", "screenshot"],
                    "step_selector": ["", "", ""],
                    "step_text": ["", "", ""],
                    "step_value": ["", "", ""],
                    "step_timeout_ms": ["", "1000", ""],
                    "step_name": ["", "", "launch"],
                    "step_metric": ["", "", ""],
                    "step_min": ["", "", ""],
                    "step_max": ["", "", ""],
                    },
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            builder_suite = store.load_suite("builder-suite")
            self.assertEqual(builder_suite.name, "Builder Suite")
            self.assertEqual(builder_suite.thresholds.metrics["launch_time_ms"].max, 5000)
            self.assertEqual(builder_suite.thresholds.metrics["appium_command_max_ms"].max, 500)
            self.assertEqual(builder_suite.thresholds.metrics["cpu_percent"].max, 80)
            self.assertEqual(builder_suite.thresholds.metrics["logcat_error_count"].max, 0)

            response = client.post(
                "/suites/builder",
                data=_with_csrf(
                    app,
                    {
                    "suite_name": "Extended Suite",
                    "target_mode": "apk",
                    "apk": "app.apk",
                    "max_duration_ms": "30000",
                    "max_assertion_failures": "0",
                    "max_metric_violations": "0",
                    "scenario_name": "extended smoke",
                    "step_action": [
                        "launch_app",
                        "terminate_app",
                        "activate_app",
                        "background_app",
                        "swipe",
                        "scroll_to_text",
                        "assert_not_text",
                        "assert_visible",
                        "assert_not_exists",
                        "assert_attribute",
                        "assert_current_package",
                        "assert_current_activity",
                    ],
                    "step_selector": [
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "id=com.example:id/login",
                        "id=com.example:id/error",
                        "id=com.example:id/login",
                        "",
                        "",
                    ],
                    "step_text": [
                        "",
                        "",
                        "",
                        "",
                        "",
                        "Terms",
                        "Error",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ],
                    "step_value": ["", "", "", "", "", "", "", "", "", "true", "", ""],
                    "step_timeout_ms": [
                        "",
                        "",
                        "",
                        "1500",
                        "",
                        "8000",
                        "5000",
                        "5000",
                        "5000",
                        "5000",
                        "",
                        "",
                    ],
                    "step_name": ["", "", "", "", "", "", "", "", "", "", "", ""],
                    "step_metric": ["", "", "", "", "", "", "", "", "", "", "", ""],
                    "step_direction": ["", "", "", "", "up", "", "", "", "", "", "", ""],
                    "step_percent": ["", "", "", "", "0.75", "", "", "", "", "", "", ""],
                    "step_attribute": ["", "", "", "", "", "", "", "", "", "enabled", "", ""],
                    "step_package": [
                        "",
                        "com.example",
                        "com.example",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "com.example",
                        "",
                    ],
                    "step_activity": [
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "*.MainActivity",
                    ],
                    "step_min": ["", "", "", "", "", "", "", "", "", "", "", ""],
                    "step_max": ["", "", "", "", "", "", "", "", "", "", "", ""],
                    },
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            extended_suite = store.load_suite("extended-suite")
            self.assertEqual(extended_suite.scenarios[0].steps[1].package, "com.example")
            self.assertEqual(extended_suite.scenarios[0].steps[3].timeout_ms, 1500)
            self.assertEqual(extended_suite.scenarios[0].steps[4].direction, "up")
            self.assertEqual(extended_suite.scenarios[0].steps[4].percent, 0.75)
            self.assertEqual(extended_suite.scenarios[0].steps[9].attribute, "enabled")
            self.assertEqual(extended_suite.scenarios[0].steps[10].package, "com.example")
            self.assertEqual(extended_suite.scenarios[0].steps[11].activity, "*.MainActivity")

            response = client.post(
                "/suites/builder",
                data=_with_csrf(
                    app,
                    {
                    "suite_name": "Installed Suite",
                    "target_mode": "installed",
                    "app_package": "com.hspace.testapp",
                    "app_activity": ".MainActivity",
                    "app_wait_activity": ".MainActivity",
                    "app_wait_package": "com.hspace.testapp",
                    "max_duration_ms": "30000",
                    "max_assertion_failures": "0",
                    "max_metric_violations": "0",
                    "scenario_name": "installed smoke",
                    "step_action": ["launch_app", "wait", "screenshot"],
                    "step_selector": ["", "", ""],
                    "step_text": ["", "", ""],
                    "step_value": ["", "", ""],
                    "step_timeout_ms": ["", "1000", ""],
                    "step_name": ["", "", "installed"],
                    "step_metric": ["", "", ""],
                    "step_min": ["", "", ""],
                    "step_max": ["", "", ""],
                    },
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            installed_suite = store.load_suite("installed-suite")
            self.assertEqual(installed_suite.app.app_package, "com.hspace.testapp")
            self.assertEqual(installed_suite.app.app_activity, ".MainActivity")
            self.assertEqual(installed_suite.app.app_wait_package, "com.hspace.testapp")

            response = client.post(
                "/suites/builder-suite/delete",
                data=_with_csrf(app),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIsNone(store.get_suite_summary("builder-suite"))

            orphan_dir = store.artifact_dir_for_run("orphan-run")
            (orphan_dir / "screen.png").write_text("png", encoding="utf-8")
            response = client.post(
                "/settings/maintenance/prune-runs",
                data=_with_csrf(
                    app,
                    {
                        "keep_last": "1",
                        "older_than_days": "0",
                        "delete_orphan_artifacts": "true",
                    },
                ),
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIsNone(store.get_run_detail("run-old"))
            self.assertIsNotNone(store.get_run_detail("run-web"))
            self.assertFalse(orphan_dir.exists())

    def test_readiness_checks_configured_free_disk_threshold(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_MIN_FREE_DISK_MB": "10",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            with patch("sla_app.web.app.shutil.disk_usage", return_value=SimpleNamespace(free=11 * 1024 * 1024)):
                response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            disk_check = next(check for check in response.json()["checks"] if check["name"] == "disk_free")
            self.assertEqual(disk_check["status"], "ok")

            with patch("sla_app.web.app.shutil.disk_usage", return_value=SimpleNamespace(free=9 * 1024 * 1024)):
                response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            disk_check = next(check for check in response.json()["checks"] if check["name"] == "disk_free")
            self.assertEqual(disk_check["status"], "fail")
            self.assertIn("free_mb=9", disk_check["detail"])
            self.assertIn("required_mb=10", disk_check["detail"])

    def test_readiness_can_require_appium_server(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_READY_CHECK_APPIUM": "",
                    "APPIUM_URL": "http://appium.example:4723",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("appium_server", {check["name"] for check in response.json()["checks"]})

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_READY_CHECK_APPIUM": "true",
                    "APPIUM_URL": "http://appium.example:4723",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            with patch("sla_app.web.app.is_appium_server_ready", return_value=False) as ready:
                response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            ready.assert_called_once_with("http://appium.example:4723")
            appium_check = next(check for check in response.json()["checks"] if check["name"] == "appium_server")
            self.assertEqual(appium_check["status"], "fail")
            self.assertIn("unreachable", appium_check["detail"])

            with patch("sla_app.web.app.is_appium_server_ready", return_value=True):
                response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            appium_check = next(check for check in response.json()["checks"] if check["name"] == "appium_server")
            self.assertEqual(appium_check["status"], "ok")
            self.assertIn("ready", appium_check["detail"])

    def test_csrf_protects_unsafe_routes(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_CSRF_SECRET": "test-csrf-secret",
                    "SLA_TRUSTED_ORIGINS": "https://trusted.example",
                    "SLA_ALLOWED_HOSTS": "",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            response = client.post("/suites", data={"yaml_text": VALID_YAML}, follow_redirects=False)
            self.assertEqual(response.status_code, 403)

            response = client.post(
                "/suites",
                data={"yaml_text": VALID_YAML, "csrf_token": "wrong"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 403)

            response = client.post(
                "/suites",
                data=_with_csrf(app, {"yaml_text": VALID_YAML}),
                headers={"Origin": "https://evil.example"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 403)

            response = client.post(
                "/suites",
                data=_with_csrf(app, {"yaml_text": VALID_YAML}),
                headers={"Origin": "http://testserver"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

            response = client.post(
                "/suites",
                data=_with_csrf(app, {"yaml_text": VALID_YAML.replace("Web Suite", "Trusted Suite")}),
                headers={"Origin": "https://trusted.example"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

    def test_allowed_hosts_restricts_untrusted_host_headers(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "testserver,good.example",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            self.assertEqual(client.get("/", headers={"Host": "testserver"}).status_code, 200)
            self.assertEqual(client.get("/", headers={"Host": "evil.example"}).status_code, 400)

            response = client.get("/version", headers={"Host": "good.example"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["allowed_hosts"], ["testserver", "good.example"])

    def test_suite_run_is_processed_by_background_queue(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        started = threading.Event()
        release = threading.Event()

        class BlockingAdapter:
            def launch_app(self) -> None:
                started.set()
                self.released = release.wait(timeout=5)

            def close(self) -> None:
                pass

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_RUN_WORKERS": "1",
                    "SLA_RUN_QUEUE_LIMIT": "1",
                },
            ),
        ):
            app = create_app(tmp)
            store = app.state.store
            summary = store.save_suite(suite_from_yaml_text(VALID_YAML), VALID_YAML)
            client = TestClient(app)
            try:
                with patch("sla_app.web.app.AndroidAppiumAdapter.from_suite", return_value=BlockingAdapter()):
                    response = client.post(
                        f"/suites/{summary.suite_id}/runs",
                        data=_with_csrf(app),
                        follow_redirects=False,
                    )
                    self.assertEqual(response.status_code, 303)
                    run_id = response.headers["location"].rsplit("/", 1)[-1]
                    self.assertTrue(started.wait(timeout=2))
                    self.assertEqual(store.get_run_detail(run_id)["status"], "RUNNING")

                    metrics = client.get("/metrics").text
                    self.assertIn("sla_run_queue_reserved 1", metrics)
                    self.assertIn("sla_run_queue_running 1", metrics)
                    self.assertIn("sla_run_queue_queued 0", metrics)
                    self.assertIn("sla_run_queue_available 0", metrics)
                    self.assertIn("sla_run_queue_accepted_total 1", metrics)
                    version_queue = client.get("/version").json()["runtime"]["run_queue"]
                    self.assertEqual(version_queue["queue_limit"], 1)
                    self.assertEqual(version_queue["reserved"], 1)
                    self.assertEqual(version_queue["running"], 1)
                    self.assertEqual(version_queue["queued"], 0)
                    self.assertEqual(version_queue["available"], 0)

                    run_page = client.get(f"/runs/{run_id}").text
                    self.assertIn("실행 중", run_page)
                    self.assertIn("http-equiv=\"refresh\"", run_page)

                    response = client.post(
                        f"/suites/{summary.suite_id}/runs",
                        data=_with_csrf(app),
                        follow_redirects=False,
                    )
                    self.assertEqual(response.status_code, 429)
                    self.assertIn("sla_run_queue_rejected_total 1", client.get("/metrics").text)

                    release.set()
                    self.assertEqual(_wait_for_run_status(store, run_id, "PASS"), "PASS")
                    _wait_for_metrics_line(client, "sla_run_queue_completed_total 1")
                    metrics = client.get("/metrics").text
                    self.assertIn("sla_run_queue_reserved 0", metrics)
                    self.assertIn("sla_run_queue_running 0", metrics)
                    self.assertIn("sla_run_queue_available 1", metrics)
                    final_page = client.get(f"/runs/{run_id}").text
                    self.assertIn("SLA 통과", final_page)
                    self.assertNotIn("http-equiv=\"refresh\"", final_page)
            finally:
                release.set()
                app.state.run_queue.shutdown()

    def test_startup_recovers_incomplete_background_runs(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
            from sla_app.storage import SqliteStore
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_RECOVER_INCOMPLETE_RUNS": "true",
                },
            ),
        ):
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)
            store.save_run(
                RunRecord(
                    run_id="interrupted-run",
                    suite_id=summary.suite_id,
                    suite_name=suite.name,
                    status="RUNNING",
                    started_at="2026-04-23T00:00:00+00:00",
                    ended_at="2026-04-23T00:00:00+00:00",
                    duration_ms=0,
                    assertion_failures=0,
                    metric_violations=0,
                    reasons=["background execution started"],
                    artifact_dir=str(store.artifact_dir_for_run("interrupted-run")),
                )
            )

            app = create_app(tmp)
            client = TestClient(app)
            detail = app.state.store.get_run_detail("interrupted-run")

            self.assertEqual(detail["status"], "ERROR")
            self.assertIn("server restarted before background execution completed", detail["reasons"])
            response = client.get("/version")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["recovered_incomplete_runs"], 1)

    def test_shutdown_marks_queued_background_runs_as_error(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        started = threading.Event()
        release = threading.Event()
        first_run_id = ""

        class BlockingAdapter:
            def launch_app(self) -> None:
                started.set()
                release.wait(timeout=5)

            def close(self) -> None:
                pass

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_ALLOWED_HOSTS": "",
                    "SLA_RUN_WORKERS": "1",
                    "SLA_RUN_QUEUE_LIMIT": "2",
                },
            ),
        ):
            app = create_app(tmp)
            store = app.state.store
            summary = store.save_suite(suite_from_yaml_text(VALID_YAML), VALID_YAML)
            try:
                with patch("sla_app.web.app.AndroidAppiumAdapter.from_suite", return_value=BlockingAdapter()):
                    with TestClient(app) as client:
                        first = client.post(
                            f"/suites/{summary.suite_id}/runs",
                            data=_with_csrf(app),
                            follow_redirects=False,
                        )
                        self.assertEqual(first.status_code, 303)
                        first_run_id = first.headers["location"].rsplit("/", 1)[-1]
                        self.assertTrue(started.wait(timeout=2))

                        second = client.post(
                            f"/suites/{summary.suite_id}/runs",
                            data=_with_csrf(app),
                            follow_redirects=False,
                        )
                        self.assertEqual(second.status_code, 303)
                        second_run_id = second.headers["location"].rsplit("/", 1)[-1]
                        self.assertEqual(store.get_run_detail(second_run_id)["status"], "QUEUED")

                queued_detail = store.get_run_detail(second_run_id)
                self.assertEqual(queued_detail["status"], "ERROR")
                self.assertIn(
                    "server shut down before background execution started",
                    queued_detail["reasons"],
                )
                self.assertEqual(store.get_run_detail(first_run_id)["status"], "RUNNING")
            finally:
                release.set()
                if first_run_id:
                    self.assertEqual(_wait_for_run_status(store, first_run_id, "PASS"), "PASS")

    def test_production_readiness_requires_security_configuration(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "production",
                    "SLA_BUILD_SHA": "local",
                    "SLA_BASIC_AUTH_USER": "",
                    "SLA_BASIC_AUTH_PASSWORD": "",
                    "SLA_CSRF_SECRET": "",
                    "SLA_TRUSTED_ORIGINS": "",
                    "SLA_ALLOWED_HOSTS": "",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            deployment_check = next(
                check for check in response.json()["checks"] if check["name"] == "deployment_config"
            )
            self.assertEqual(deployment_check["status"], "fail")
            self.assertIn("SLA_BASIC_AUTH_USER/SLA_BASIC_AUTH_PASSWORD", deployment_check["detail"])
            self.assertIn("SLA_CSRF_SECRET", deployment_check["detail"])

            response = client.get("/version")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["deployment_config_ok"], False)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "production",
                    "SLA_BUILD_SHA": "abc123",
                    "SLA_BASIC_AUTH_USER": "operator",
                    "SLA_BASIC_AUTH_PASSWORD": "change-me",
                    "SLA_CSRF_SECRET": "long-random-secret",
                    "SLA_TRUSTED_ORIGINS": "http://testserver",
                    "SLA_ALLOWED_HOSTS": "testserver",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            deployment_check = next(
                check for check in response.json()["checks"] if check["name"] == "deployment_config"
            )
            self.assertEqual(deployment_check["status"], "fail")
            self.assertIn("SLA_BASIC_AUTH_PASSWORD_WEAK", deployment_check["detail"])
            self.assertIn("SLA_CSRF_SECRET_WEAK", deployment_check["detail"])

            response = client.get(
                "/version",
                headers={"Authorization": _basic_auth_header("operator", "change-me")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["deployment_config_ok"], False)
            self.assertIn(
                "SLA_BASIC_AUTH_PASSWORD_WEAK",
                response.json()["runtime"]["deployment_issues"],
            )

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "production",
                    "SLA_BUILD_SHA": "abc123",
                    "SLA_BASIC_AUTH_USER": "operator",
                    "SLA_BASIC_AUTH_PASSWORD": "verify-production-password-32chars",
                    "SLA_CSRF_SECRET": "verify-production-csrf-secret-32chars",
                    "SLA_TRUSTED_ORIGINS": "http://testserver",
                    "SLA_ALLOWED_HOSTS": "testserver",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            response = client.get("/readyz")
            self.assertEqual(response.status_code, 200)
            deployment_check = next(
                check for check in response.json()["checks"] if check["name"] == "deployment_config"
            )
            self.assertEqual(deployment_check["status"], "ok")

            response = client.get(
                "/version",
                headers={
                    "Authorization": _basic_auth_header(
                        "operator",
                        "verify-production-password-32chars",
                    )
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["deployment_config_ok"], True)
            self.assertEqual(response.json()["runtime"]["deployment_issues"], [])

    def test_basic_auth_protects_app_when_configured(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from sla_app.web.app import create_app
        except ImportError as exc:
            self.skipTest(f"web dependencies are not installed: {exc}")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                "os.environ",
                {
                    "SLA_ENV": "local",
                    "SLA_BASIC_AUTH_USER": "operator",
                    "SLA_BASIC_AUTH_PASSWORD": "secret",
                    "SLA_ALLOWED_HOSTS": "",
                },
            ),
        ):
            app = create_app(tmp)
            client = TestClient(app)

            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/readyz").status_code, 200)

            with self.assertLogs("sla_app.web.app", level="INFO") as logs:
                response = client.get("/", headers={"X-Request-ID": "auth-denied"})
            self.assertEqual(response.status_code, 401)
            self.assertIn("Basic", response.headers["www-authenticate"])
            self.assertEqual(response.headers["x-request-id"], "auth-denied")
            self.assertIn("request_id=auth-denied", "\n".join(logs.output))
            self.assertIn("status=401", "\n".join(logs.output))

            response = client.get("/")
            self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")

            self.assertEqual(client.get("/version").status_code, 401)
            self.assertEqual(client.get("/metrics").status_code, 401)

            response = client.get("/", headers={"Authorization": _basic_auth_header("operator", "wrong")})
            self.assertEqual(response.status_code, 401)

            response = client.get("/", headers={"Authorization": _basic_auth_header("operator", "secret")})
            self.assertEqual(response.status_code, 200)
            metrics = client.get(
                "/metrics",
                headers={"Authorization": _basic_auth_header("operator", "secret")},
            ).text
            self.assertIn('sla_http_requests_total{method="GET",path="/",status="401"}', metrics)
            self.assertIn('sla_http_requests_total{method="GET",path="/version",status="401"}', metrics)

            response = client.get(
                "/version",
                headers={"Authorization": _basic_auth_header("operator", "secret")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["runtime"]["auth_enabled"], True)

            response = client.get(
                "/metrics",
                headers={"Authorization": _basic_auth_header("operator", "secret")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("sla_info", response.text)


def _basic_auth_header(username: str, password: str) -> str:
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {credentials}"


def _wait_for_metrics_line(client, expected_line: str, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        last_text = client.get("/metrics").text
        if expected_line in last_text:
            return last_text
        time.sleep(0.05)
    raise AssertionError(f"metrics did not contain {expected_line!r}:\n{last_text}")


def _with_csrf(app, data=None):
    payload = {"csrf_token": app.state.csrf_token}
    if data:
        payload.update(data)
    return payload


def _wait_for_run_status(store, run_id: str, expected: str) -> str:
    deadline = time.time() + 3
    last_status = ""
    while time.time() < deadline:
        detail = store.get_run_detail(run_id)
        last_status = detail["status"] if detail else ""
        if last_status == expected:
            return last_status
        time.sleep(0.05)
    return last_status


if __name__ == "__main__":
    unittest.main()
