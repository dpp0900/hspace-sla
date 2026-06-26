from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

import yaml

from sla_app import __version__


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def test_dockerfile_runs_web_app_as_non_root_user(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("ARG SLA_BUILD_SHA", dockerfile)
        self.assertIn("SLA_APP_HOME=/data", dockerfile)
        self.assertIn("SLA_DB_PATH=/data/db/sla_app.db", dockerfile)
        self.assertIn("SLA_PROXY_HEADERS=true", dockerfile)
        self.assertIn("SLA_FORWARDED_ALLOW_IPS=127.0.0.1", dockerfile)
        self.assertIn("USER sla", dockerfile)
        self.assertIn("HEALTHCHECK --interval=30s --timeout=5s", dockerfile)
        self.assertIn("/readyz", dockerfile)
        self.assertIn("SLA_WEB_PORT", dockerfile)
        self.assertIn('CMD ["python", "-m", "sla_app.web"]', dockerfile)

    def test_dockerignore_excludes_local_state_and_secrets(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        for pattern in (
            ".git",
            ".env",
            ".env.*",
            "!.env.example",
            "sla_app.db",
            "*.db-wal",
            "*.db-shm",
            "artifacts",
            ".pytest_cache",
            ".coverage",
            "htmlcov",
            ".venv",
            "**/__pycache__",
            "*.py[cod]",
            "**/*.py[cod]",
            "dist",
            "build",
            "*.egg-info",
            "node_modules",
            "*.log",
            "*.zip",
        ):
            self.assertIn(pattern, dockerignore)

    def test_compose_persists_state_and_checks_readiness(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        service = compose["services"]["sla-web"]

        self.assertEqual(service["ports"], ["8010:8000"])
        self.assertIs(service["init"], True)
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(service["stop_grace_period"], "${SLA_CONTAINER_STOP_GRACE_PERIOD:-45s}")
        self.assertIs(service["read_only"], True)
        self.assertEqual(service["tmpfs"], ["/tmp:rw,noexec,nosuid,size=64m"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["build"]["args"]["SLA_BUILD_SHA"], "${SLA_BUILD_SHA:-local}")
        self.assertEqual(service["environment"]["SLA_ENV"], "${SLA_ENV:-local}")
        self.assertEqual(service["environment"]["SLA_BUILD_SHA"], "${SLA_BUILD_SHA:-local}")
        self.assertEqual(service["environment"]["SLA_DB_PATH"], "/data/db/sla_app.db")
        self.assertEqual(service["environment"]["SLA_PROXY_HEADERS"], "${SLA_PROXY_HEADERS:-true}")
        self.assertEqual(
            service["environment"]["SLA_FORWARDED_ALLOW_IPS"],
            "${SLA_FORWARDED_ALLOW_IPS:-127.0.0.1}",
        )
        self.assertEqual(service["environment"]["SLA_ROOT_PATH"], "${SLA_ROOT_PATH:-}")
        self.assertEqual(
            service["environment"]["SLA_GRACEFUL_SHUTDOWN_TIMEOUT"],
            "${SLA_GRACEFUL_SHUTDOWN_TIMEOUT:-30}",
        )
        self.assertEqual(service["environment"]["SLA_LOG_LEVEL"], "${SLA_LOG_LEVEL:-INFO}")
        self.assertEqual(service["environment"]["SLA_MIN_FREE_DISK_MB"], "${SLA_MIN_FREE_DISK_MB:-0}")
        self.assertEqual(
            service["environment"]["SLA_READY_CHECK_APPIUM"],
            "${SLA_READY_CHECK_APPIUM:-false}",
        )
        self.assertEqual(service["environment"]["SLA_BASIC_AUTH_USER"], "${SLA_BASIC_AUTH_USER:-}")
        self.assertEqual(
            service["environment"]["SLA_BASIC_AUTH_PASSWORD"],
            "${SLA_BASIC_AUTH_PASSWORD:-}",
        )
        self.assertEqual(service["environment"]["SLA_CSRF_SECRET"], "${SLA_CSRF_SECRET:-}")
        self.assertEqual(service["environment"]["SLA_TRUSTED_ORIGINS"], "${SLA_TRUSTED_ORIGINS:-}")
        self.assertEqual(service["environment"]["SLA_ALLOWED_HOSTS"], "${SLA_ALLOWED_HOSTS:-}")
        self.assertEqual(service["environment"]["SLA_RUN_WORKERS"], "${SLA_RUN_WORKERS:-1}")
        self.assertEqual(service["environment"]["SLA_RUN_QUEUE_LIMIT"], "${SLA_RUN_QUEUE_LIMIT:-10}")
        self.assertEqual(
            service["environment"]["SLA_RECOVER_INCOMPLETE_RUNS"],
            "${SLA_RECOVER_INCOMPLETE_RUNS:-true}",
        )
        self.assertIn("sla-db:/data/db", service["volumes"])
        self.assertIn("readyz", " ".join(service["healthcheck"]["test"]))
        self.assertIn("sla-db", compose["volumes"])

    def test_readme_documents_container_entrypoints(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("docker compose up --build", readme)
        self.assertIn(".dockerignore", readme)
        self.assertIn("SLA_DB_PATH", readme)
        self.assertIn("SLA_BASIC_AUTH_USER", readme)
        self.assertIn("SLA_FORWARDED_ALLOW_IPS", readme)
        self.assertIn("SLA_CONTAINER_STOP_GRACE_PERIOD", readme)
        self.assertIn("SLA_READY_CHECK_APPIUM", readme)
        self.assertIn("SLA_LOG_LEVEL", readme)
        self.assertIn("Docker 이미지 자체에도 `/readyz` 기반 healthcheck", readme)
        self.assertIn("read-only root filesystem", readme)
        self.assertIn("cap_drop: ALL", readme)
        self.assertIn("no-new-privileges", readme)
        self.assertIn("schema version", readme)
        self.assertIn("skipped_unsafe_files", readme)
        self.assertIn("SLA_RETENTION_KEEP_LAST", readme)
        self.assertIn("/settings/backup.zip", readme)
        self.assertIn("GET /readyz", readme)
        self.assertIn("GET /metrics", readme)
        self.assertIn("X-Request-ID", readme)

    def test_ci_runs_python_and_container_smoke_checks(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn('python -m pip install -e ".[dev]"', workflow)
        self.assertIn("python -m pytest tests", workflow)
        self.assertIn("docker compose config", workflow)
        self.assertIn("docker build --build-arg SLA_BUILD_SHA=${{ github.sha }}", workflow)
        self.assertIn("-t hspace-sla-runner:ci .", workflow)
        self.assertIn("docker port sla-ci 8000/tcp", workflow)
        self.assertIn("--read-only", workflow)
        self.assertIn("--tmpfs /tmp:rw,noexec,nosuid,size=64m", workflow)
        self.assertIn("--cap-drop ALL", workflow)
        self.assertIn("--security-opt no-new-privileges", workflow)
        self.assertIn('${base}/readyz', workflow)
        self.assertIn('${base}/version', workflow)
        self.assertIn('${base}/metrics', workflow)
        self.assertIn("Smoke test Docker image in production mode", workflow)
        self.assertIn("SLA_ENV=production", workflow)
        self.assertIn("SLA_BASIC_AUTH_USER=operator", workflow)
        self.assertIn("verify-production-password-32chars", workflow)
        self.assertIn("verify-production-csrf-secret-32chars", workflow)
        self.assertIn("docker port sla-ci-prod 8000/tcp", workflow)
        self.assertIn('${base}/readyz', workflow)
        self.assertIn('"deployment_config_ok":true', workflow)
        self.assertIn('-u "operator:${password}" "${base}/metrics"', workflow)

    def test_pyproject_exposes_release_entrypoints(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]

        self.assertEqual(pyproject["project"]["version"], "0.1.0")
        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(scripts["sla-web"], "sla_app.web.__main__:main")
        self.assertEqual(scripts["sla-launch-android"], "sla_launcher.main:main")
        self.assertEqual(scripts["sla-restore-backup"], "scripts.restore_backup:main")
        self.assertEqual(scripts["sla-mcp"], "sla_app.mcp.server:main")
        self.assertIn("mcp==1.28.0", pyproject["project"]["dependencies"])

    def test_project_mcp_config_is_read_only_by_default(self) -> None:
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["hspace-sla"]

        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["-m", "sla_app.mcp"])
        self.assertEqual(server["env"]["SLA_MCP_ALLOW_WRITES"], "false")
        self.assertEqual(server["env"]["SLA_MCP_ALLOW_RUNS"], "false")

    def test_env_example_documents_operational_settings(self) -> None:
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("SLA_ENV=production", env_example)
        self.assertIn("SLA_BUILD_SHA=", env_example)
        self.assertIn("SLA_BASIC_AUTH_USER=", env_example)
        self.assertIn("SLA_PROXY_HEADERS=true", env_example)
        self.assertIn("SLA_FORWARDED_ALLOW_IPS=127.0.0.1", env_example)
        self.assertIn("SLA_ROOT_PATH=", env_example)
        self.assertIn("SLA_GRACEFUL_SHUTDOWN_TIMEOUT=30", env_example)
        self.assertIn("SLA_CONTAINER_STOP_GRACE_PERIOD=45s", env_example)
        self.assertIn("placeholders fail readiness", env_example)
        self.assertIn("SLA_LOG_LEVEL=INFO", env_example)
        self.assertIn("SLA_MIN_FREE_DISK_MB=0", env_example)
        self.assertIn("SLA_READY_CHECK_APPIUM=false", env_example)
        self.assertIn("SLA_CSRF_SECRET=", env_example)
        self.assertIn("SLA_TRUSTED_ORIGINS=", env_example)
        self.assertIn("SLA_ALLOWED_HOSTS=", env_example)
        self.assertIn("SLA_RUN_WORKERS=1", env_example)
        self.assertIn("SLA_RUN_QUEUE_LIMIT=10", env_example)
        self.assertIn("SLA_RECOVER_INCOMPLETE_RUNS=true", env_example)
        self.assertIn("SLA_MCP_TRANSPORT=stdio", env_example)
        self.assertIn("SLA_MCP_LOG_LEVEL=WARNING", env_example)
        self.assertIn("SLA_MCP_ALLOW_WRITES=false", env_example)
        self.assertIn("SLA_MCP_ALLOW_RUNS=false", env_example)
        self.assertIn("SLA_RETENTION_DAYS=30", env_example)

    def test_makefile_has_release_check(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("docker-production-smoke", makefile)
        self.assertIn("release-check: compile test docker-smoke docker-production-smoke", makefile)
        self.assertIn("docker-smoke", makefile)
        self.assertIn("DOCKER_RUN_HARDENING", makefile)
        self.assertIn("--read-only", makefile)
        self.assertIn("--cap-drop ALL", makefile)
        self.assertIn("--security-opt no-new-privileges", makefile)
        self.assertIn("docker compose config", makefile)
        self.assertIn("docker port hspace-sla-verify 8000/tcp", makefile)
        self.assertIn("$${base}/version", makefile)
        self.assertIn("$${base}/metrics", makefile)
        self.assertIn("SLA_ENV=production", makefile)
        self.assertIn("verify-production-password-32chars", makefile)
        self.assertIn("verify-production-csrf-secret-32chars", makefile)
        self.assertIn("docker port hspace-sla-prod-verify 8000/tcp", makefile)
        self.assertIn("$${base}/readyz", makefile)
        self.assertIn("deployment_config_ok", makefile)

    def test_operations_guide_documents_backup_restore_and_version(self) -> None:
        operations = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")

        self.assertIn("/version", operations)
        self.assertIn("sla-restore-backup", operations)
        self.assertIn("Docker 이미지와 Compose healthcheck", operations)
        self.assertIn("root filesystem은 읽기 전용", operations)
        self.assertIn("Linux capabilities는 모두 제거", operations)
        self.assertIn("no-new-privileges", operations)
        self.assertIn("SLA_BUILD_SHA", operations)
        self.assertIn("SLA_CSRF_SECRET", operations)
        self.assertIn("SLA_PROXY_HEADERS", operations)
        self.assertIn("SLA_FORWARDED_ALLOW_IPS", operations)
        self.assertIn("SLA_ROOT_PATH", operations)
        self.assertIn("SLA_GRACEFUL_SHUTDOWN_TIMEOUT", operations)
        self.assertIn("SLA_CONTAINER_STOP_GRACE_PERIOD", operations)
        self.assertIn("SLA_LOG_LEVEL", operations)
        self.assertIn("SLA_MIN_FREE_DISK_MB", operations)
        self.assertIn("SLA_READY_CHECK_APPIUM", operations)
        self.assertIn("SLA_TRUSTED_ORIGINS", operations)
        self.assertIn("SLA_ALLOWED_HOSTS", operations)
        self.assertIn("SLA_RUN_WORKERS", operations)
        self.assertIn("SLA_RUN_QUEUE_LIMIT", operations)
        self.assertIn("SLA_RECOVER_INCOMPLETE_RUNS", operations)
        self.assertIn("SLA_RETENTION_KEEP_LAST", operations)
        self.assertIn("/metrics", operations)
        self.assertIn("X-Request-ID", operations)
        self.assertIn("정상 shutdown", operations)
        self.assertIn("disk_free", operations)
        self.assertIn("sla_http_requests_total", operations)
        self.assertIn("sla_run_queue_", operations)
        self.assertIn("user_version", operations)
        self.assertIn("skipped_unsafe_files", operations)

    def test_mcp_guide_documents_llm_setup(self) -> None:
        guide = (ROOT / "docs" / "mcp.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("python3 -m sla_app.mcp", guide)
        self.assertIn("sla-mcp", guide)
        self.assertIn("SLA_MCP_ALLOW_WRITES", guide)
        self.assertIn("SLA_MCP_ALLOW_RUNS", guide)
        self.assertIn("Claude Desktop", guide)
        self.assertIn("Claude Code", guide)
        self.assertIn("list_suites", guide)
        self.assertIn("run_suite", guide)
        self.assertIn("docs/mcp.md", readme)


if __name__ == "__main__":
    unittest.main()
