from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path


def restore_backup(
    backup_path: str | Path,
    *,
    base_dir: str | Path,
    db_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, str]:
    backup = Path(backup_path)
    target_base = Path(base_dir)
    target_db = Path(db_path) if db_path is not None else target_base / "sla_app.db"
    suites_dir = target_base / "suites"
    artifacts_dir = target_base / "artifacts"

    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
        _validate_backup(names)
        if not force:
            _guard_empty_target(target_db, suites_dir, artifacts_dir)

        target_base.mkdir(parents=True, exist_ok=True)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        _replace_directory(suites_dir)
        _replace_directory(artifacts_dir)
        suites_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        _restore_file(archive, "database/sla_app.db", target_db)
        _restore_prefix(archive, "suites/", suites_dir)
        _restore_prefix(archive, "artifacts/", artifacts_dir)

    return {
        "base_dir": str(target_base),
        "db_path": str(target_db),
        "suites_dir": str(suites_dir),
        "artifacts_dir": str(artifacts_dir),
    }


def _validate_backup(names: set[str]) -> None:
    required = {"manifest.json", "database/sla_app.db"}
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"backup is missing required entries: {', '.join(missing)}")


def _guard_empty_target(db_path: Path, suites_dir: Path, artifacts_dir: Path) -> None:
    occupied = []
    if db_path.exists():
        occupied.append(str(db_path))
    for directory in (suites_dir, artifacts_dir):
        if directory.exists() and any(directory.iterdir()):
            occupied.append(str(directory))
    if occupied:
        raise FileExistsError(
            "restore target already contains data; pass --force to replace it: "
            + ", ".join(occupied)
        )


def _replace_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _restore_file(archive: zipfile.ZipFile, source_name: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".restore-tmp")
    with archive.open(source_name) as source, temporary.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    temporary.replace(target)


def _restore_prefix(archive: zipfile.ZipFile, prefix: str, target_root: Path) -> None:
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        relative = Path(info.filename[len(prefix) :])
        if not relative.parts:
            continue
        target = target_root / relative
        _ensure_within(target, target_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)


def _ensure_within(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"unsafe backup path: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore an SLA Test Runner backup ZIP")
    parser.add_argument("backup_zip", help="Path to backup ZIP downloaded from /settings/backup.zip")
    parser.add_argument("--base-dir", default=".", help="Target SLA_APP_HOME directory")
    parser.add_argument("--db-path", default=None, help="Target SQLite path, defaults to <base-dir>/sla_app.db")
    parser.add_argument("--force", action="store_true", help="Replace existing DB, suites, and artifacts")
    args = parser.parse_args(argv)

    try:
        result = restore_backup(
            args.backup_zip,
            base_dir=args.base_dir,
            db_path=args.db_path,
            force=args.force,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should print the actionable restore failure.
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1

    print(f"restored base_dir={result['base_dir']}")
    print(f"restored db_path={result['db_path']}")
    print(f"restored suites_dir={result['suites_dir']}")
    print(f"restored artifacts_dir={result['artifacts_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
