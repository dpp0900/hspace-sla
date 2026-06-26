from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sla_app.core.models import RunRecord, TestSuite
from sla_app.core.yaml_loader import load_suite, suite_to_yaml


DB_SCHEMA_VERSION = 1
DB_BUSY_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class SuiteSummary:
    suite_id: str
    name: str
    yaml_path: Path
    updated_at: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    suite_id: str
    suite_name: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    assertion_failures: int
    metric_violations: int
    reasons: list[str]
    artifact_dir: str


class SqliteStore:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)
        self.suites_dir = self.base_dir / "suites"
        self.artifacts_dir = self.base_dir / "artifacts"
        self.db_path = Path(os.getenv("SLA_DB_PATH", self.base_dir / "sla_app.db"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.suites_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save_suite(self, suite: TestSuite, yaml_text: str | None = None) -> SuiteSummary:
        suite_id = suite.suite_id or slugify_suite_id(suite.name)
        yaml_path = self.suites_dir / f"{suite_id}.yaml"
        yaml_path.write_text(yaml_text if yaml_text is not None else suite_to_yaml(suite), encoding="utf-8")
        return self.register_suite_file(suite_id, suite, yaml_path)

    def register_suite_file(
        self,
        suite_id: str,
        suite: TestSuite,
        yaml_path: str | Path,
    ) -> SuiteSummary:
        yaml_path = Path(yaml_path)
        now = _utc_now()
        with self._managed_connection() as conn:
            conn.execute(
                """
                INSERT INTO suites (id, name, yaml_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    yaml_path=excluded.yaml_path,
                    updated_at=excluded.updated_at
                """,
                (suite_id, suite.name, str(yaml_path), now, now),
            )
        return SuiteSummary(suite_id=suite_id, name=suite.name, yaml_path=yaml_path, updated_at=now)

    def list_suites(self) -> list[SuiteSummary]:
        with self._managed_connection() as conn:
            rows = conn.execute(
                "SELECT id, name, yaml_path, updated_at FROM suites ORDER BY updated_at DESC"
            ).fetchall()
        return [
            SuiteSummary(
                suite_id=row["id"],
                name=row["name"],
                yaml_path=Path(row["yaml_path"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_suite_summary(self, suite_id: str) -> SuiteSummary | None:
        with self._managed_connection() as conn:
            row = conn.execute(
                "SELECT id, name, yaml_path, updated_at FROM suites WHERE id = ?",
                (suite_id,),
            ).fetchone()
        if row is None:
            return None
        return SuiteSummary(
            suite_id=row["id"],
            name=row["name"],
            yaml_path=Path(row["yaml_path"]),
            updated_at=row["updated_at"],
        )

    def load_suite(self, suite_id: str) -> TestSuite:
        summary = self.get_suite_summary(suite_id)
        if summary is None:
            raise KeyError(f"suite not found: {suite_id}")
        suite = load_suite(summary.yaml_path)
        return TestSuite(
            name=suite.name,
            app=suite.app,
            thresholds=suite.thresholds,
            scenarios=suite.scenarios,
            suite_id=suite_id,
            source_path=summary.yaml_path,
        )

    def get_suite_yaml(self, suite_id: str) -> str:
        summary = self.get_suite_summary(suite_id)
        if summary is None:
            raise KeyError(f"suite not found: {suite_id}")
        return summary.yaml_path.read_text(encoding="utf-8")

    def delete_suite(self, suite_id: str) -> bool:
        summary = self.get_suite_summary(suite_id)
        if summary is None:
            return False

        with self._managed_connection() as conn:
            conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))

        self._delete_owned_suite_file(summary.yaml_path)
        return True

    def _delete_owned_suite_file(self, yaml_path: Path) -> None:
        try:
            resolved_path = yaml_path.resolve()
            suites_root = self.suites_dir.resolve()
            if resolved_path.is_file() and suites_root in resolved_path.parents:
                resolved_path.unlink()
        except OSError:
            return

    def artifact_dir_for_run(self, run_id: str) -> Path:
        artifact_dir = self.artifacts_dir / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def save_run(self, run: RunRecord) -> None:
        detail = run.to_dict()
        with self._managed_connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, suite_id, suite_name, status, started_at, ended_at,
                    duration_ms, assertion_failures, metric_violations,
                    reasons_json, artifact_dir, detail_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    ended_at=excluded.ended_at,
                    duration_ms=excluded.duration_ms,
                    assertion_failures=excluded.assertion_failures,
                    metric_violations=excluded.metric_violations,
                    reasons_json=excluded.reasons_json,
                    artifact_dir=excluded.artifact_dir,
                    detail_json=excluded.detail_json
                """,
                (
                    run.run_id,
                    run.suite_id,
                    run.suite_name,
                    run.status,
                    run.started_at,
                    run.ended_at,
                    run.duration_ms,
                    run.assertion_failures,
                    run.metric_violations,
                    json.dumps(run.reasons),
                    run.artifact_dir,
                    json.dumps(detail),
                ),
            )

    def list_runs(self, limit: int = 20) -> list[RunSummary]:
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, suite_id, suite_name, status, started_at, ended_at,
                       duration_ms, assertion_failures, metric_violations,
                       reasons_json, artifact_dir
                FROM runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_run_summary_from_row(row) for row in rows]

    def list_runs_for_suite(self, suite_id: str, limit: int = 20) -> list[RunSummary]:
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, suite_id, suite_name, status, started_at, ended_at,
                       duration_ms, assertion_failures, metric_violations,
                       reasons_json, artifact_dir
                FROM runs
                WHERE suite_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (suite_id, limit),
            ).fetchall()
        return [_run_summary_from_row(row) for row in rows]

    def get_run_summary(self, run_id: str) -> RunSummary | None:
        with self._managed_connection() as conn:
            row = conn.execute(
                """
                SELECT id, suite_id, suite_name, status, started_at, ended_at,
                       duration_ms, assertion_failures, metric_violations,
                       reasons_json, artifact_dir
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return _run_summary_from_row(row) if row else None

    def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        with self._managed_connection() as conn:
            row = conn.execute(
                "SELECT detail_json FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["detail_json"])

    def run_counts(self) -> dict[str, int]:
        with self._managed_connection() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM runs GROUP BY status").fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def run_count(self) -> int:
        with self._managed_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()
        return int(row["count"])

    def fail_incomplete_runs(
        self,
        *,
        reason: str,
        statuses: tuple[str, ...] = ("QUEUED", "RUNNING"),
        now: datetime | None = None,
    ) -> int:
        if not statuses:
            return 0

        completed_at = now or datetime.now(UTC)
        completed_at_text = completed_at.isoformat()
        placeholders = ",".join("?" for _ in statuses)
        with self._managed_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, status, started_at, duration_ms, assertion_failures,
                       metric_violations, reasons_json, detail_json
                FROM runs
                WHERE status IN ({placeholders})
                """,
                statuses,
            ).fetchall()

            for row in rows:
                detail = json.loads(row["detail_json"])
                reasons = list(detail.get("reasons") or json.loads(row["reasons_json"]))
                if reason not in reasons:
                    reasons.append(reason)
                started_at = str(detail.get("started_at") or row["started_at"])
                duration_ms = max(
                    int(row["duration_ms"]),
                    _duration_ms_between(started_at, completed_at),
                )
                detail.update(
                    {
                        "status": "ERROR",
                        "ended_at": completed_at_text,
                        "duration_ms": duration_ms,
                        "assertion_failures": int(row["assertion_failures"]),
                        "metric_violations": int(row["metric_violations"]),
                        "reasons": reasons,
                    }
                )
                conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, ended_at = ?, duration_ms = ?, reasons_json = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (
                        "ERROR",
                        completed_at_text,
                        duration_ms,
                        json.dumps(reasons),
                        json.dumps(detail),
                        row["id"],
                    ),
                )
        return len(rows)

    def database_status(self) -> dict[str, object]:
        with self._managed_connection() as conn:
            run_count = conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"]
            suite_count = conn.execute("SELECT COUNT(*) AS count FROM suites").fetchone()["count"]
            return {
                "path": str(self.db_path),
                "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
                "expected_schema_version": DB_SCHEMA_VERSION,
                "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]),
                "synchronous": int(conn.execute("PRAGMA synchronous").fetchone()[0]),
                "busy_timeout_ms": int(conn.execute("PRAGMA busy_timeout").fetchone()[0]),
                "quick_check": str(conn.execute("PRAGMA quick_check(1)").fetchone()[0]),
                "run_count": int(run_count),
                "suite_count": int(suite_count),
            }

    def backup_database(self, destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as source, closing(sqlite3.connect(destination_path)) as target:
            source.backup(target)
        return destination_path

    def prune_runs(
        self,
        *,
        keep_last: int | None = None,
        older_than_days: int | None = None,
    ) -> dict[str, object]:
        if keep_last is not None and keep_last < 0:
            raise ValueError("keep_last must be greater than or equal to 0")
        if older_than_days is not None and older_than_days < 0:
            raise ValueError("older_than_days must be greater than or equal to 0")
        if keep_last is None and older_than_days is None:
            raise ValueError("keep_last or older_than_days is required")

        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, started_at, artifact_dir
                FROM runs
                ORDER BY started_at DESC
                """
            ).fetchall()

        protected_ids = {row["id"] for row in rows[:keep_last]} if keep_last is not None else set()
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days) if older_than_days is not None else None

        rows_to_delete = []
        for row in rows:
            if row["id"] in protected_ids:
                continue
            if cutoff is not None and _parse_datetime(row["started_at"]) >= cutoff:
                continue
            rows_to_delete.append(row)

        run_ids = [row["id"] for row in rows_to_delete]
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            with self._managed_connection() as conn:
                conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", run_ids)

        deleted_artifact_dirs = 0
        for row in rows_to_delete:
            if self._delete_run_artifact_dir(Path(row["artifact_dir"])):
                deleted_artifact_dirs += 1

        return {
            "deleted_runs": len(run_ids),
            "deleted_artifact_dirs": deleted_artifact_dirs,
            "run_ids": run_ids,
        }

    def prune_orphan_artifacts(self) -> int:
        with self._managed_connection() as conn:
            run_ids = {row["id"] for row in conn.execute("SELECT id FROM runs").fetchall()}

        deleted = 0
        if not self.artifacts_dir.exists():
            return deleted
        for path in self.artifacts_dir.iterdir():
            if not path.is_dir() or path.name in run_ids:
                continue
            if self._delete_run_artifact_dir(path):
                deleted += 1
        return deleted

    def _initialize(self) -> None:
        with self._managed_connection() as conn:
            current_schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current_schema_version > DB_SCHEMA_VERSION:
                raise RuntimeError(
                    "database schema is newer than this application supports: "
                    f"current={current_schema_version} expected={DB_SCHEMA_VERSION}"
                )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS suites (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    yaml_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    suite_id TEXT NOT NULL,
                    suite_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    assertion_failures INTEGER NOT NULL,
                    metric_violations INTEGER NOT NULL,
                    reasons_json TEXT NOT NULL,
                    artifact_dir TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );
                """
            )
            if current_schema_version < DB_SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        self._apply_connection_pragmas(conn)
        return conn

    def _apply_connection_pragmas(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

    @contextmanager
    def _managed_connection(self):
        with closing(self._connect()) as conn:
            with conn:
                yield conn

    def _delete_run_artifact_dir(self, artifact_dir: Path) -> bool:
        try:
            resolved_path = artifact_dir.resolve()
            artifacts_root = self.artifacts_dir.resolve()
            if resolved_path.is_dir() and artifacts_root in resolved_path.parents:
                shutil.rmtree(resolved_path)
                return True
        except OSError:
            return False
        return False


def slugify_suite_id(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "suite"


def _run_summary_from_row(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        run_id=row["id"],
        suite_id=row["suite_id"],
        suite_name=row["suite_name"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_ms=int(row["duration_ms"]),
        assertion_failures=int(row["assertion_failures"]),
        metric_violations=int(row["metric_violations"]),
        reasons=json.loads(row["reasons_json"]),
        artifact_dir=row["artifact_dir"],
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _duration_ms_between(started_at: str, ended_at: datetime) -> int:
    try:
        started = _parse_datetime(started_at)
    except (TypeError, ValueError):
        return 0
    return max(0, int((ended_at - started).total_seconds() * 1000))
