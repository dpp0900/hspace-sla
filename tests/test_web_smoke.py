from __future__ import annotations

import tempfile
import unittest

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
            for path in ("/", "/suites", "/runs/run-web", "/settings"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
