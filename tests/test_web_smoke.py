from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from sla_app.core.models import RunRecord
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

        with tempfile.TemporaryDirectory() as tmp:
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
                )
            )

            client = TestClient(app)
            for path in (
                "/",
                "/suites",
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

            with patch(
                "sla_app.web.app._installed_apps_payload",
                return_value={
                    "device": "emulator-5554",
                    "apps": [
                        {
                            "label": "HSPACE Test App",
                            "package": "com.hspace.testapp",
                            "activity": ".MainActivity",
                        }
                    ],
                },
            ):
                response = client.get("/android/installed-apps")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["apps"][0]["package"], "com.hspace.testapp")

            response = client.post(
                f"/suites/{summary.suite_id}/edit/helper",
                data={
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
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            edited_suite = store.load_suite(summary.suite_id)
            self.assertEqual(edited_suite.name, "Edited Web Suite")
            self.assertEqual(edited_suite.app.apk, "edited.apk")
            self.assertEqual(edited_suite.scenarios[0].steps[1].timeout_ms, 500)

            class FakeAdapter:
                def inspect_elements(self):
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

            with patch("sla_app.web.app.AndroidAppiumAdapter.from_suite", return_value=FakeAdapter()):
                response = client.get(f"/suites/{summary.suite_id}/elements")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["elements"][0]["selector"], "id=com.example:id/email")

            response = client.post(
                "/suites/builder",
                data={
                    "suite_name": "Builder Suite",
                    "target_mode": "apk",
                    "apk": "app.apk",
                    "max_duration_ms": "30000",
                    "max_assertion_failures": "0",
                    "max_metric_violations": "0",
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
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(store.load_suite("builder-suite").name, "Builder Suite")

            response = client.post(
                "/suites/builder",
                data={
                    "suite_name": "Installed Suite",
                    "target_mode": "installed",
                    "app_package": "com.hspace.testapp",
                    "app_activity": ".MainActivity",
                    "app_wait_activity": ".MainActivity",
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
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            installed_suite = store.load_suite("installed-suite")
            self.assertEqual(installed_suite.app.app_package, "com.hspace.testapp")
            self.assertEqual(installed_suite.app.app_activity, ".MainActivity")

            response = client.post("/suites/builder-suite/delete", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIsNone(store.get_suite_summary("builder-suite"))


if __name__ == "__main__":
    unittest.main()
