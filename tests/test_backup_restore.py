from __future__ import annotations

import json
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.restore_backup import main as restore_main
from scripts.restore_backup import restore_backup
from sla_app.core.models import RunRecord
from sla_app.core.yaml_loader import suite_from_yaml_text
from sla_app.web.app import create_app


VALID_YAML = """name: Restore Suite
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: launch_app
"""


class BackupRestoreTests(unittest.TestCase):
    def test_restores_backup_zip_into_empty_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            restore_dir = Path(tmp) / "restore"
            backup_path = Path(tmp) / "backup.zip"
            app = create_app(source_dir)
            store = app.state.store
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)
            artifact_dir = store.artifact_dir_for_run("restore-run")
            (artifact_dir / "screen.png").write_text("png", encoding="utf-8")
            store.save_run(
                RunRecord(
                    run_id="restore-run",
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
            )

            response = TestClient(app).get("/settings/backup.zip")
            self.assertEqual(response.status_code, 200)
            backup_path.write_bytes(response.content)

            result = restore_backup(backup_path, base_dir=restore_dir)

            self.assertEqual(result["base_dir"], str(restore_dir))
            with sqlite3.connect(restore_dir / "sla_app.db") as conn:
                suite_count = conn.execute("SELECT COUNT(*) FROM suites").fetchone()[0]
                run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            self.assertEqual(suite_count, 1)
            self.assertEqual(run_count, 1)
            self.assertTrue((restore_dir / "suites" / "restore-suite.yaml").exists())
            self.assertTrue((restore_dir / "artifacts" / "restore-run" / "screen.png").exists())

    def test_backup_zip_skips_symlinks_outside_data_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            app = create_app(source_dir)
            store = app.state.store
            suite = suite_from_yaml_text(VALID_YAML)
            store.save_suite(suite, VALID_YAML)
            outside_secret = Path(tmp) / "outside-secret.txt"
            outside_secret.write_text("do not back up", encoding="utf-8")
            linked_secret = store.artifacts_dir / "linked-secret.txt"
            try:
                os.symlink(outside_secret, linked_secret)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation is not supported: {exc}")

            response = TestClient(app).get("/settings/backup.zip")

            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.content)) as backup:
                names = set(backup.namelist())
                manifest = json.loads(backup.read("manifest.json"))
            self.assertNotIn("artifacts/linked-secret.txt", names)
            self.assertGreaterEqual(manifest["skipped_unsafe_files"], 1)

    def test_restore_requires_force_for_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            restore_dir = Path(tmp) / "restore"
            backup_path = Path(tmp) / "backup.zip"
            app = create_app(source_dir)
            response = TestClient(app).get("/settings/backup.zip")
            backup_path.write_bytes(response.content)
            restore_dir.mkdir()
            (restore_dir / "sla_app.db").write_text("existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                restore_backup(backup_path, base_dir=restore_dir)

            restore_backup(backup_path, base_dir=restore_dir, force=True)
            self.assertGreater((restore_dir / "sla_app.db").stat().st_size, 0)

    def test_restore_cli_returns_nonzero_for_invalid_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_backup = Path(tmp) / "invalid.zip"
            invalid_backup.write_text("not a zip", encoding="utf-8")

            self.assertEqual(restore_main([str(invalid_backup), "--base-dir", str(Path(tmp) / "restore")]), 1)


if __name__ == "__main__":
    unittest.main()
