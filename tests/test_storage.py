from __future__ import annotations

import tempfile
import unittest

from sla_app.core.models import RunRecord
from sla_app.core.yaml_loader import suite_from_yaml_text
from sla_app.storage import SqliteStore


VALID_YAML = """name: Storage Suite
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: launch_app
"""


class StorageTests(unittest.TestCase):
    def test_saves_suite_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)

            self.assertEqual(summary.suite_id, "storage-suite")
            self.assertEqual(store.load_suite(summary.suite_id).name, "Storage Suite")

            artifact_dir = store.artifact_dir_for_run("run-1")
            run = RunRecord(
                run_id="run-1",
                suite_id=summary.suite_id,
                suite_name=suite.name,
                status="PASS",
                started_at="2026-04-23T00:00:00+00:00",
                ended_at="2026-04-23T00:00:01+00:00",
                duration_ms=1000,
                assertion_failures=0,
                metric_violations=0,
                reasons=[],
                artifact_dir=str(artifact_dir),
            )
            store.save_run(run)

            self.assertEqual(store.list_runs()[0].run_id, "run-1")
            self.assertEqual(store.get_run_detail("run-1")["status"], "PASS")
            self.assertTrue(artifact_dir.exists())

    def test_registers_existing_suite_without_rewriting_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite_path = store.suites_dir / "example_android.yaml"
            suite_path.write_text(VALID_YAML, encoding="utf-8")

            summary = store.register_suite_file(
                "example_android",
                suite_from_yaml_text(VALID_YAML, source_path=suite_path),
                suite_path,
            )

            self.assertEqual(summary.suite_id, "example_android")
            self.assertEqual(summary.yaml_path, suite_path)
            self.assertFalse((store.suites_dir / "storage-suite.yaml").exists())

    def test_deletes_suite_registration_and_owned_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)

            self.assertTrue(summary.yaml_path.exists())
            self.assertTrue(store.delete_suite(summary.suite_id))

            self.assertIsNone(store.get_suite_summary(summary.suite_id))
            self.assertFalse(summary.yaml_path.exists())
            self.assertFalse(store.delete_suite(summary.suite_id))


if __name__ == "__main__":
    unittest.main()
