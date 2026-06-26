from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sla_app.core.models import RunRecord
from sla_app.core.yaml_loader import suite_from_yaml_text
from sla_app.storage import SqliteStore
from sla_app.storage.sqlite_store import DB_BUSY_TIMEOUT_MS, DB_SCHEMA_VERSION


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

    def test_lists_runs_for_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)

            for run_id, suite_id, started_at in (
                ("run-1", summary.suite_id, "2026-04-23T00:00:00+00:00"),
                ("run-other", "other-suite", "2026-04-24T00:00:00+00:00"),
                ("run-2", summary.suite_id, "2026-04-25T00:00:00+00:00"),
            ):
                store.save_run(
                    RunRecord(
                        run_id=run_id,
                        suite_id=suite_id,
                        suite_name=suite.name,
                        status="PASS",
                        started_at=started_at,
                        ended_at=started_at,
                        duration_ms=1000,
                        assertion_failures=0,
                        metric_violations=0,
                        reasons=[],
                        artifact_dir=str(store.artifact_dir_for_run(run_id)),
                    )
                )

            runs = store.list_runs_for_suite(summary.suite_id)

            self.assertEqual([run.run_id for run in runs], ["run-2", "run-1"])

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

    def test_uses_configured_database_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "app"
            db_path = Path(tmp) / "db" / "sla.sqlite3"

            with patch.dict("os.environ", {"SLA_DB_PATH": str(db_path)}):
                store = SqliteStore(base_dir)

            self.assertEqual(store.db_path, db_path)
            self.assertTrue(db_path.exists())
            self.assertTrue((base_dir / "suites").exists())

    def test_database_status_reports_operational_pragmas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            status = store.database_status()

            self.assertEqual(status["schema_version"], DB_SCHEMA_VERSION)
            self.assertEqual(status["expected_schema_version"], DB_SCHEMA_VERSION)
            self.assertEqual(status["journal_mode"], "wal")
            self.assertEqual(status["busy_timeout_ms"], DB_BUSY_TIMEOUT_MS)
            self.assertEqual(status["quick_check"], "ok")

    def test_rejects_newer_database_schema_without_downgrading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "future.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION + 1}")

            with (
                patch.dict("os.environ", {"SLA_DB_PATH": str(db_path)}),
                self.assertRaisesRegex(RuntimeError, "database schema is newer"),
            ):
                SqliteStore(Path(tmp) / "app")

            with sqlite3.connect(db_path) as conn:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(version, DB_SCHEMA_VERSION + 1)

    def test_marks_incomplete_runs_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)

            for run_id, status in (("queued-run", "QUEUED"), ("running-run", "RUNNING"), ("pass-run", "PASS")):
                store.save_run(
                    RunRecord(
                        run_id=run_id,
                        suite_id=summary.suite_id,
                        suite_name=suite.name,
                        status=status,
                        started_at="2026-04-23T00:00:00+00:00",
                        ended_at="2026-04-23T00:00:00+00:00",
                        duration_ms=0,
                        assertion_failures=0,
                        metric_violations=0,
                        reasons=[],
                        artifact_dir=str(store.artifact_dir_for_run(run_id)),
                    )
                )

            recovered = store.fail_incomplete_runs(
                reason="server restarted before background execution completed",
                now=datetime(2026, 4, 23, 0, 0, 3, tzinfo=UTC),
            )

            self.assertEqual(recovered, 2)
            queued = store.get_run_detail("queued-run")
            running = store.get_run_detail("running-run")
            passed = store.get_run_detail("pass-run")
            self.assertEqual(queued["status"], "ERROR")
            self.assertEqual(running["status"], "ERROR")
            self.assertEqual(queued["duration_ms"], 3000)
            self.assertIn("server restarted before background execution completed", running["reasons"])
            self.assertEqual(passed["status"], "PASS")

    def test_backs_up_database_with_sqlite_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            store.save_suite(suite, VALID_YAML)

            backup_path = store.backup_database(Path(tmp) / "backup" / "sla_app.db")

            with sqlite3.connect(backup_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM suites").fetchone()
            self.assertEqual(row[0], 1)

    def test_prunes_old_runs_and_artifact_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            suite = suite_from_yaml_text(VALID_YAML)
            summary = store.save_suite(suite, VALID_YAML)

            for run_id, started_at in (
                ("run-1", "2026-04-23T00:00:00+00:00"),
                ("run-2", "2026-04-24T00:00:00+00:00"),
                ("run-3", "2026-04-25T00:00:00+00:00"),
            ):
                artifact_dir = store.artifact_dir_for_run(run_id)
                (artifact_dir / "screen.png").write_text("png", encoding="utf-8")
                store.save_run(
                    RunRecord(
                        run_id=run_id,
                        suite_id=summary.suite_id,
                        suite_name=suite.name,
                        status="PASS",
                        started_at=started_at,
                        ended_at=started_at,
                        duration_ms=1000,
                        assertion_failures=0,
                        metric_violations=0,
                        reasons=[],
                        artifact_dir=str(artifact_dir),
                    )
                )

            result = store.prune_runs(keep_last=1, older_than_days=0)

            self.assertEqual(result["deleted_runs"], 2)
            self.assertEqual([run.run_id for run in store.list_runs()], ["run-3"])
            self.assertFalse((store.artifacts_dir / "run-1").exists())
            self.assertFalse((store.artifacts_dir / "run-2").exists())
            self.assertTrue((store.artifacts_dir / "run-3").exists())

    def test_prunes_orphan_artifact_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(tmp)
            orphan_dir = store.artifacts_dir / "orphan-run"
            orphan_dir.mkdir()
            (orphan_dir / "screen.png").write_text("png", encoding="utf-8")

            self.assertEqual(store.prune_orphan_artifacts(), 1)
            self.assertFalse(orphan_dir.exists())


if __name__ == "__main__":
    unittest.main()
