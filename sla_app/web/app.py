from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import os
import platform
import secrets
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, Lock
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sla_app import __version__
from sla_app.adapters.android_appium import AndroidAppiumAdapter
from sla_app.adapters.android_appium.installed_apps import list_launchable_apps
from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.models import (
    ActionStep,
    AppTarget,
    MetricLimit,
    RunRecord,
    Scenario,
    SlaThresholds,
    TestSuite,
)
from sla_app.core.yaml_loader import SuiteValidationError, suite_from_yaml_text, suite_to_yaml
from sla_app.storage import SqliteStore
from sla_launcher.android import avd_home, detect_host_architecture, ensure_emulator, load_avd_definitions
from sla_launcher.appium_server import is_appium_server_ready
from sla_launcher.config import LaunchConfig
from sla_launcher.diagnostics import collect_environment_diagnostics
from sla_launcher.paths import default_sdk_root, platform_executable_name, sdk_tool_path
from sla_launcher.process import resolve_executable, resolve_sdk_root


PACKAGE_DIR = Path(__file__).parent
LOGGER = logging.getLogger(__name__)
_PRODUCTION_PLACEHOLDER_SECRETS = {
    "admin",
    "change-me",
    "changeme",
    "example",
    "long-random-secret",
    "operator",
    "password",
    "secret",
    "stable-secret",
    "test",
    "test-csrf-secret",
}
_MIN_PRODUCTION_PASSWORD_LENGTH = 16
_MIN_PRODUCTION_CSRF_SECRET_LENGTH = 32


class HttpMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._series: dict[tuple[str, str, str], tuple[int, float]] = {}

    def record(self, *, method: str, path: str, status_code: int, duration_ms: int) -> None:
        key = (method.upper(), path, str(status_code))
        duration_seconds = max(0, duration_ms) / 1000
        with self._lock:
            count, total_seconds = self._series.get(key, (0, 0.0))
            self._series[key] = (count + 1, total_seconds + duration_seconds)

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            series = list(self._series.items())
        return [
            {
                "method": method,
                "path": path,
                "status": status,
                "count": count,
                "duration_seconds_sum": duration_seconds_sum,
            }
            for (method, path, status), (count, duration_seconds_sum) in sorted(series)
        ]


DEFAULT_SUITE_YAML = """name: Android Smoke
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
scenarios:
  - name: launch and capture
    steps:
      - action: launch_app
      - action: wait
        timeout_ms: 1000
      - action: screenshot
        name: launch
"""


class RunQueue:
    def __init__(self, *, max_workers: int, queue_limit: int) -> None:
        self.max_workers = max_workers
        self.queue_limit = max(queue_limit, max_workers)
        self._capacity = BoundedSemaphore(self.queue_limit)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sla-run")
        self._lock = Lock()
        self._reserved = 0
        self._running = 0
        self._accepted_total = 0
        self._completed_total = 0
        self._rejected_total = 0

    def try_acquire(self) -> bool:
        acquired = self._capacity.acquire(blocking=False)
        with self._lock:
            if acquired:
                self._reserved += 1
                self._accepted_total += 1
            else:
                self._rejected_total += 1
        return acquired

    def release_acquired(self) -> None:
        self._capacity.release()
        with self._lock:
            self._reserved = max(0, self._reserved - 1)

    def submit_acquired(self, fn: Callable[[], None]) -> None:
        def run_and_release() -> None:
            self._mark_running_started()
            try:
                fn()
            finally:
                self._mark_running_completed()
                self._capacity.release()
                with self._lock:
                    self._reserved = max(0, self._reserved - 1)

        try:
            self._executor.submit(run_and_release)
        except RuntimeError:
            self.release_acquired()
            raise

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            reserved = self._reserved
            running = self._running
            return {
                "max_workers": self.max_workers,
                "queue_limit": self.queue_limit,
                "reserved": reserved,
                "running": running,
                "queued": max(0, reserved - running),
                "available": max(0, self.queue_limit - reserved),
                "accepted_total": self._accepted_total,
                "completed_total": self._completed_total,
                "rejected_total": self._rejected_total,
            }

    def _mark_running_started(self) -> None:
        with self._lock:
            self._running += 1

    def _mark_running_completed(self) -> None:
        with self._lock:
            self._running = max(0, self._running - 1)
            self._completed_total += 1


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        yield
    finally:
        run_queue = getattr(app.state, "run_queue", None)
        if run_queue is not None:
            run_queue.shutdown()
        store = getattr(app.state, "store", None)
        if store is not None:
            _fail_queued_runs_on_shutdown(store)


def create_app(base_dir: str | Path | None = None) -> FastAPI:
    app_base_dir = Path(base_dir or os.getenv("SLA_APP_HOME", ".")).resolve()
    store = SqliteStore(app_base_dir)
    _import_existing_suites(store)
    recovered_incomplete_runs = _recover_incomplete_runs_on_startup(store)

    app = FastAPI(title="SLA 테스트 러너", lifespan=_lifespan)
    app.state.store = store
    app.state.csrf_token = _csrf_token_from_secret(_csrf_secret_from_env())
    app.state.trusted_origins = _trusted_origins_from_env()
    app.state.allowed_hosts = _allowed_hosts_from_env()
    if app.state.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=app.state.allowed_hosts)
    app.state.run_queue = _run_queue_from_env()
    app.state.http_metrics = HttpMetrics()
    app.state.recovered_incomplete_runs = recovered_incomplete_runs
    auth_config = _basic_auth_config_from_env()
    app.state.auth_enabled = auth_config is not None
    if auth_config is not None:
        _install_basic_auth(app, username=auth_config[0], password=auth_config[1])
    _install_security_headers(app)
    _install_request_id(app)

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    templates.env.filters["artifact_url"] = _artifact_url_filter(store)
    templates.env.globals["csrf_token"] = app.state.csrf_token

    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    app.mount("/artifacts", StaticFiles(directory=str(store.artifacts_dir)), name="artifacts")

    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"status": "ok", "service": "sla-test-runner", "version": __version__})

    @app.get("/readyz")
    async def readyz():
        payload = _readiness_payload(
            store,
            auth_enabled=app.state.auth_enabled,
            allowed_hosts=app.state.allowed_hosts,
            trusted_origins=app.state.trusted_origins,
        )
        return JSONResponse(payload, status_code=200 if payload["status"] == "ok" else 503)

    @app.get("/version")
    async def version():
        return JSONResponse(
            _version_payload(
                store,
                auth_enabled=app.state.auth_enabled,
                allowed_hosts=app.state.allowed_hosts,
                trusted_origins=app.state.trusted_origins,
                run_queue=app.state.run_queue,
                recovered_incomplete_runs=app.state.recovered_incomplete_runs,
            )
        )

    @app.get("/metrics")
    async def metrics():
        return Response(
            _metrics_payload(store, app.state.run_queue, app.state.http_metrics),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        counts = store.run_counts()
        runs = store.list_runs(limit=10)
        suite_count = len(store.list_suites())
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "active": "dashboard",
                "counts": counts,
                "run_total": sum(counts.values()),
                "runs": runs,
                "suite_count": suite_count,
                "dashboard_signals": _dashboard_signals(runs),
            },
        )

    @app.get("/suites", response_class=HTMLResponse)
    async def suites(request: Request):
        return templates.TemplateResponse(
            request,
            "suites.html",
            {
                "active": "suites",
                "suites": store.list_suites(),
            },
        )

    @app.get("/suites/builder", response_class=HTMLResponse)
    async def suite_builder(request: Request):
        return templates.TemplateResponse(
            request,
            "suite_builder.html",
            {
                "active": "suites",
                "title": "쉬운 생성기",
                "eyebrow": "코드 없이 스위트 만들기",
                "action": "/suites/builder",
                "back_url": "/suites",
                "yaml_url": "/suites/new",
                "submit_label": "스위트 저장",
                "inspect_url": "/android/elements",
                "installed_apps_url": "/android/installed-apps",
                "builder": _default_builder_state(),
                "error": None,
                "notice": None,
            },
        )

    @app.post("/suites/builder", dependencies=[Depends(_require_csrf)])
    async def create_suite_from_builder(request: Request):
        form = await request.form()
        builder = _builder_state_from_form(form)
        try:
            yaml_text = _builder_state_to_yaml(builder)
            suite = suite_from_yaml_text(yaml_text)
        except (SuiteValidationError, ValueError) as exc:
            return templates.TemplateResponse(
                request,
                "suite_builder.html",
                {
                    "active": "suites",
                    "title": "쉬운 생성기",
                    "eyebrow": "코드 없이 스위트 만들기",
                    "action": "/suites/builder",
                    "back_url": "/suites",
                    "yaml_url": "/suites/new",
                    "submit_label": "스위트 저장",
                    "inspect_url": "/android/elements",
                    "installed_apps_url": "/android/installed-apps",
                    "builder": builder,
                    "error": str(exc),
                    "notice": None,
                },
                status_code=400,
            )
        store.save_suite(suite, yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/suites/new", response_class=HTMLResponse)
    async def new_suite(request: Request):
        return templates.TemplateResponse(
            request,
            "suite_form.html",
            {
                "active": "suites",
                "title": "새 스위트",
                "action": "/suites",
                "yaml_text": DEFAULT_SUITE_YAML,
                "error": None,
            },
        )

    @app.post("/suites", dependencies=[Depends(_require_csrf)])
    async def create_suite(request: Request, yaml_text: str = Form(...)):
        try:
            suite = suite_from_yaml_text(yaml_text)
        except SuiteValidationError as exc:
            return templates.TemplateResponse(
                request,
                "suite_form.html",
                {
                    "active": "suites",
                    "title": "새 스위트",
                    "action": "/suites",
                    "yaml_text": yaml_text,
                    "error": str(exc),
                },
                status_code=400,
            )
        store.save_suite(suite, yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/suites/{suite_id}", response_class=HTMLResponse)
    async def suite_detail(request: Request, suite_id: str):
        summary = _suite_summary_or_404(store, suite_id)
        runs = store.list_runs_for_suite(suite_id, limit=20)
        latest_detail = store.get_run_detail(runs[0].run_id) if runs else None
        previous_detail = store.get_run_detail(runs[1].run_id) if len(runs) > 1 else None
        return templates.TemplateResponse(
            request,
            "suite_detail.html",
            {
                "active": "suites",
                "suite": summary,
                "runs": runs,
                "suite_signals": _suite_signals(runs),
                "metric_summary": _run_metric_summary(latest_detail, previous_detail)
                if latest_detail
                else [],
                "run_history": _run_history_from_summaries(runs, runs[0].run_id if runs else ""),
            },
        )

    @app.get("/suites/{suite_id}/edit", response_class=HTMLResponse)
    async def choose_edit_mode(request: Request, suite_id: str):
        summary = _suite_summary_or_404(store, suite_id)
        try:
            suite = store.load_suite(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        helper_available, helper_reasons = _builder_compatibility(suite)
        return templates.TemplateResponse(
            request,
            "suite_edit_choice.html",
            {
                "active": "suites",
                "suite": summary,
                "helper_available": helper_available,
                "helper_reasons": helper_reasons,
            },
        )

    @app.get("/suites/{suite_id}/edit/helper", response_class=HTMLResponse)
    async def edit_suite_with_helper(request: Request, suite_id: str):
        try:
            suite = store.load_suite(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        helper_available, helper_reasons = _builder_compatibility(suite)
        if not helper_available:
            return templates.TemplateResponse(
                request,
                "suite_edit_choice.html",
                {
                    "active": "suites",
                    "suite": _suite_summary_or_404(store, suite_id),
                    "helper_available": helper_available,
                    "helper_reasons": helper_reasons,
                },
                status_code=400,
            )
        return templates.TemplateResponse(
            request,
            "suite_builder.html",
            {
                "active": "suites",
                "title": "쉬운 편집",
                "eyebrow": "가이드 편집",
                "action": f"/suites/{suite_id}/edit/helper",
                "back_url": f"/suites/{suite_id}/edit",
                "yaml_url": f"/suites/{suite_id}/edit/yaml",
                "submit_label": "변경 저장",
                "inspect_url": "/android/elements",
                "installed_apps_url": "/android/installed-apps",
                "builder": _builder_state_from_suite(suite),
                "error": None,
                "notice": "쉬운 편집기는 지원하는 필드만 수정하고 같은 스위트 ID로 저장합니다.",
            },
        )

    @app.post("/suites/{suite_id}/edit/helper", dependencies=[Depends(_require_csrf)])
    async def update_suite_from_helper(request: Request, suite_id: str):
        if store.get_suite_summary(suite_id) is None:
            raise HTTPException(status_code=404, detail="스위트를 찾지 못했습니다")
        form = await request.form()
        builder = _builder_state_from_form(form)
        try:
            yaml_text = _builder_state_to_yaml(builder)
            suite = suite_from_yaml_text(yaml_text)
        except (SuiteValidationError, ValueError) as exc:
            return templates.TemplateResponse(
                request,
                "suite_builder.html",
                {
                    "active": "suites",
                    "title": "쉬운 편집",
                    "eyebrow": "가이드 편집",
                    "action": f"/suites/{suite_id}/edit/helper",
                    "back_url": f"/suites/{suite_id}/edit",
                    "yaml_url": f"/suites/{suite_id}/edit/yaml",
                    "submit_label": "변경 저장",
                    "inspect_url": "/android/elements",
                    "installed_apps_url": "/android/installed-apps",
                    "builder": builder,
                    "error": str(exc),
                    "notice": None,
                },
                status_code=400,
            )
        store.save_suite(replace(suite, suite_id=suite_id), yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/suites/{suite_id}/edit/yaml", response_class=HTMLResponse)
    async def edit_suite_yaml(request: Request, suite_id: str):
        yaml_text = _suite_yaml_or_404(store, suite_id)
        helper_url = _helper_url_if_available(store, suite_id)
        return templates.TemplateResponse(
            request,
            "suite_form.html",
            {
                "active": "suites",
                "title": "YAML 편집",
                "action": f"/suites/{suite_id}/edit/yaml",
                "yaml_text": yaml_text,
                "error": None,
                "helper_url": helper_url,
                "back_url": f"/suites/{suite_id}/edit",
            },
        )

    @app.post("/suites/{suite_id}", dependencies=[Depends(_require_csrf)])
    async def update_suite(request: Request, suite_id: str, yaml_text: str = Form(...)):
        return await update_suite_yaml(request, suite_id, yaml_text)

    @app.post("/suites/{suite_id}/edit/yaml", dependencies=[Depends(_require_csrf)])
    async def update_suite_yaml(request: Request, suite_id: str, yaml_text: str = Form(...)):
        try:
            suite = suite_from_yaml_text(yaml_text)
        except SuiteValidationError as exc:
            helper_url = _helper_url_if_available(store, suite_id)
            return templates.TemplateResponse(
                request,
                "suite_form.html",
                {
                    "active": "suites",
                    "title": "YAML 편집",
                    "action": f"/suites/{suite_id}/edit/yaml",
                    "yaml_text": yaml_text,
                    "error": str(exc),
                    "helper_url": helper_url,
                    "back_url": f"/suites/{suite_id}/edit",
                },
                status_code=400,
            )
        store.save_suite(replace(suite, suite_id=suite_id), yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/android/installed-apps")
    async def installed_apps():
        try:
            return _installed_apps_payload()
        except SystemExit as exc:
            return JSONResponse({"error": _system_exit_message(exc), "apps": []}, status_code=500)
        except Exception as exc:  # noqa: BLE001 - report local Android environment issues to the UI.
            return JSONResponse({"error": str(exc), "apps": []}, status_code=500)

    @app.get("/android/elements")
    async def inspect_android_elements(
        target_mode: str = "apk",
        apk: str = "",
        app_package: str = "",
        app_activity: str = "",
        app_wait_activity: str = "",
        app_wait_package: str = "",
        no_reset: bool = False,
        mode: str = "standard",
    ):
        try:
            app_target = _app_target_from_scan_request(
                target_mode=target_mode,
                apk=apk,
                app_package=app_package,
                app_activity=app_activity,
                app_wait_activity=app_wait_activity,
                app_wait_package=app_wait_package,
                no_reset=no_reset,
            )
            return _inspect_app_target_elements(app_target, mode=mode)
        except (SuiteValidationError, ValueError) as exc:
            return JSONResponse({"error": str(exc), "elements": []}, status_code=400)
        except Exception as exc:  # noqa: BLE001 - surface Android/Appium scan errors to the UI.
            return JSONResponse({"error": _friendly_appium_error(exc), "elements": []}, status_code=500)

    @app.get("/suites/{suite_id}/elements")
    async def inspect_suite_elements(suite_id: str, mode: str = "standard"):
        try:
            suite = store.load_suite(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return _inspect_app_target_elements(suite.app, source_path=suite.source_path, mode=mode)
        except Exception as exc:  # noqa: BLE001 - surface Appium/device scan errors to the UI.
            return JSONResponse({"error": _friendly_appium_error(exc), "elements": []}, status_code=500)

    @app.get("/suites/{suite_id}/export", response_class=PlainTextResponse)
    async def export_suite(suite_id: str):
        return PlainTextResponse(_suite_yaml_or_404(store, suite_id), media_type="text/yaml")

    @app.post("/suites/{suite_id}/delete", dependencies=[Depends(_require_csrf)])
    async def delete_suite(suite_id: str):
        if not store.delete_suite(suite_id):
            raise HTTPException(status_code=404, detail="스위트를 찾지 못했습니다")
        return RedirectResponse("/suites", status_code=303)

    @app.post("/suites/{suite_id}/runs", dependencies=[Depends(_require_csrf)])
    async def run_suite(suite_id: str):
        try:
            suite = store.load_suite(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run_queue: RunQueue = app.state.run_queue
        if not run_queue.try_acquire():
            raise HTTPException(
                status_code=429,
                detail="실행 대기열이 가득 찼습니다. 진행 중인 실행이 끝난 뒤 다시 시도하세요.",
            )

        run_id = uuid.uuid4().hex
        artifact_dir = store.artifact_dir_for_run(run_id)
        try:
            store.save_run(
                _run_status_record(
                    suite,
                    suite_id=suite_id,
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    status="QUEUED",
                    message="background execution queued",
                )
            )
        except Exception:
            run_queue.release_acquired()
            raise

        try:
            run_queue.submit_acquired(
                lambda: _execute_suite_background(
                    store,
                    suite,
                    suite_id=suite_id,
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                )
            )
        except RuntimeError as exc:
            store.save_run(
                _run_status_record(
                    suite,
                    suite_id=suite_id,
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    status="ERROR",
                    message=f"background executor is not available: {exc}",
                )
            )
            raise HTTPException(status_code=503, detail="실행 작업자를 사용할 수 없습니다") from exc
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}/report.json")
    async def run_report(run_id: str):
        payload = _run_report_payload(store, run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="실행 결과를 찾지 못했습니다")
        return JSONResponse(
            payload,
            headers={
                "Content-Disposition": f'attachment; filename="{run_id}-report.json"',
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str):
        detail = store.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="실행 결과를 찾지 못했습니다")
        comparison = _run_comparison(store, detail)
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "active": "runs",
                "run": detail,
                "insights": _run_insights(detail),
                "comparison": comparison,
                "metric_summary": _run_metric_summary(
                    detail,
                    store.get_run_detail(str(comparison["run_id"])) if comparison else None,
                ),
                "run_history": _run_history(store, detail),
            },
        )

    @app.get("/guide", response_class=HTMLResponse)
    async def yaml_guide(request: Request):
        return templates.TemplateResponse(
            request,
            "guide.html",
            {
                "active": "guide",
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        sdk_root = os.getenv("ANDROID_SDK_ROOT") or os.getenv("ANDROID_HOME") or str(default_sdk_root())
        adb_path = os.getenv("ANDROID_ADB_PATH") or sdk_tool_path(
            sdk_root,
            "platform-tools",
            platform_executable_name("adb"),
        )
        appium_url = os.getenv("APPIUM_URL", "http://127.0.0.1:4723")
        avds = []
        avd_error = None
        try:
            avds = load_avd_definitions()
        except Exception as exc:  # noqa: BLE001 - settings should report environment issues.
            avd_error = str(exc)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "active": "settings",
                "sdk_root": sdk_root,
                "sdk_exists": Path(sdk_root).expanduser().exists(),
                "adb_path": adb_path,
                "adb_exists": Path(adb_path).expanduser().exists() or shutil.which("adb"),
                "appium_url": appium_url,
                "appium_ready": is_appium_server_ready(appium_url),
                "host_arch": detect_host_architecture(),
                "avd_home": avd_home(),
                "avds": avds,
                "avd_error": avd_error,
                "maintenance": _maintenance_context(store, request, auth_enabled=app.state.auth_enabled),
            },
        )

    @app.get("/settings/backup.zip")
    async def settings_backup():
        return _backup_zip_response(store)

    @app.post("/settings/maintenance/prune-runs", dependencies=[Depends(_require_csrf)])
    async def settings_prune_runs(
        keep_last: int = Form(...),
        older_than_days: int = Form(...),
        delete_orphan_artifacts: bool = Form(False),
    ):
        try:
            result = store.prune_runs(keep_last=keep_last, older_than_days=older_than_days)
            orphan_artifacts = store.prune_orphan_artifacts() if delete_orphan_artifacts else 0
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        total_artifacts = int(result["deleted_artifact_dirs"]) + orphan_artifacts
        return RedirectResponse(
            f"/settings?maintenance=pruned&deleted_runs={result['deleted_runs']}"
            f"&deleted_artifacts={total_artifacts}",
            status_code=303,
        )

    @app.get("/settings/diagnostics")
    async def settings_diagnostics():
        return JSONResponse(collect_environment_diagnostics(_android_discovery_config()))

    return app


def _run_queue_from_env() -> RunQueue:
    max_workers = _env_positive_int("SLA_RUN_WORKERS", 1)
    queue_limit = _env_positive_int("SLA_RUN_QUEUE_LIMIT", 10)
    return RunQueue(max_workers=max_workers, queue_limit=queue_limit)


def _recover_incomplete_runs_on_startup(store: SqliteStore) -> int:
    if not _env_bool("SLA_RECOVER_INCOMPLETE_RUNS", default=True):
        return 0
    recovered = store.fail_incomplete_runs(
        reason="server restarted before background execution completed",
    )
    if recovered:
        LOGGER.warning("marked incomplete runs as ERROR on startup", extra={"run_count": recovered})
    return recovered


def _fail_queued_runs_on_shutdown(store: SqliteStore) -> int:
    failed = store.fail_incomplete_runs(
        reason="server shut down before background execution started",
        statuses=("QUEUED",),
    )
    if failed:
        LOGGER.warning("marked queued runs as ERROR on shutdown", extra={"run_count": failed})
    return failed


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_nonnegative_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _execute_suite_background(
    store: SqliteStore,
    suite: TestSuite,
    *,
    suite_id: str,
    run_id: str,
    artifact_dir: Path,
) -> None:
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    store.save_run(
        _run_status_record(
            suite,
            suite_id=suite_id,
            run_id=run_id,
            artifact_dir=artifact_dir,
            status="RUNNING",
            message="background execution started",
            started_at=started_at,
        )
    )
    try:
        adapter = AndroidAppiumAdapter.from_suite(suite)
        run = execute_suite(
            suite,
            adapter,
            suite_id=suite_id,
            options=ExecutionOptions(run_id=run_id, artifact_dir=artifact_dir),
        )
    except Exception as exc:  # noqa: BLE001 - preserve worker failures as run records.
        LOGGER.exception("background suite execution failed", extra={"run_id": run_id, "suite_id": suite_id})
        run = _run_status_record(
            suite,
            suite_id=suite_id,
            run_id=run_id,
            artifact_dir=artifact_dir,
            status="ERROR",
            message=f"background execution failed: {exc}",
            started_at=started_at,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    store.save_run(run)


def _run_status_record(
    suite: TestSuite,
    *,
    suite_id: str,
    run_id: str,
    artifact_dir: Path,
    status: str,
    message: str,
    started_at: str | None = None,
    duration_ms: int = 0,
) -> RunRecord:
    timestamp = datetime.now(UTC).isoformat()
    return RunRecord(
        run_id=run_id,
        suite_id=suite_id,
        suite_name=suite.name,
        status=status,
        started_at=started_at or timestamp,
        ended_at=timestamp,
        duration_ms=duration_ms,
        assertion_failures=0,
        metric_violations=0,
        reasons=[message] if message else [],
        artifact_dir=str(artifact_dir),
        scenarios=[],
    )


def _suite_yaml_or_404(store: SqliteStore, suite_id: str) -> str:
    try:
        return store.get_suite_yaml(suite_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _suite_summary_or_404(store: SqliteStore, suite_id: str):
    summary = store.get_suite_summary(suite_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="스위트를 찾지 못했습니다")
    return summary


def _csrf_secret_from_env() -> str:
    return os.getenv("SLA_CSRF_SECRET") or secrets.token_urlsafe(32)


def _csrf_token_from_secret(secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), b"sla-csrf-v1", hashlib.sha256).hexdigest()


def _trusted_origins_from_env() -> set[str]:
    origins = set()
    for origin in os.getenv("SLA_TRUSTED_ORIGINS", "").split(","):
        normalized = origin.strip().rstrip("/")
        if normalized:
            origins.add(normalized)
    return origins


def _allowed_hosts_from_env() -> list[str]:
    hosts = []
    for host in os.getenv("SLA_ALLOWED_HOSTS", "").split(","):
        normalized = host.strip()
        if normalized:
            hosts.append(normalized)
    return hosts


def _install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _request_id_from_header(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers.setdefault("X-Request-ID", request_id)
            return response
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            http_metrics = getattr(request.app.state, "http_metrics", None)
            if http_metrics is not None:
                http_metrics.record(
                    method=request.method,
                    path=_request_metric_path(request),
                    status_code=status_code,
                    duration_ms=duration_ms,
                )
            LOGGER.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )


def _request_metric_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return _normalized_metric_path(request.url.path)


def _normalized_metric_path(path: str) -> str:
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return "/"
    if segments[0] == "static":
        return "/static/{path:path}"
    if segments[0] == "artifacts":
        return "/artifacts/{path:path}"
    if segments[0] == "runs" and len(segments) >= 2:
        suffix = "/".join(segments[2:])
        return "/runs/{run_id}" if not suffix else f"/runs/{{run_id}}/{suffix}"
    if segments[0] == "suites" and len(segments) >= 2:
        if segments[1] == "builder":
            return "/suites/builder"
        suffix = "/".join(segments[2:])
        return "/suites/{suite_id}" if not suffix else f"/suites/{{suite_id}}/{suffix}"
    return path or "__unmatched__"


def _request_id_from_header(value: str | None) -> str:
    if value:
        candidate = value.strip()
        if 1 <= len(candidate) <= 128 and all(
            char.isalnum() or char in {"-", "_", ".", ":"} for char in candidate
        ):
            return candidate
    return uuid.uuid4().hex


def _install_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self' https://unpkg.com 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            ),
        )
        return response


async def _require_csrf(request: Request, csrf_token: str = Form("")) -> None:
    expected_token = str(request.app.state.csrf_token)
    supplied_token = request.headers.get("x-csrf-token") or csrf_token or request.query_params.get("csrf_token")
    if not supplied_token or not secrets.compare_digest(str(supplied_token), expected_token):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")

    origin = request.headers.get("origin")
    if origin and not _origin_is_allowed(request, origin):
        raise HTTPException(status_code=403, detail="Request origin is not trusted")

    referer = request.headers.get("referer")
    if not origin and referer and not _origin_is_allowed(request, _origin_from_url(referer)):
        raise HTTPException(status_code=403, detail="Request origin is not trusted")


def _origin_is_allowed(request: Request, origin: str) -> bool:
    origin = origin.rstrip("/")
    if not origin:
        return False
    return origin in {_request_origin(request), *request.app.state.trusted_origins}


def _request_origin(request: Request) -> str:
    host = request.headers.get("host") or request.url.netloc
    return f"{request.url.scheme}://{host}"


def _origin_from_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _basic_auth_config_from_env() -> tuple[str, str] | None:
    username = os.getenv("SLA_BASIC_AUTH_USER", "")
    password = os.getenv("SLA_BASIC_AUTH_PASSWORD", "")
    if not username and not password:
        return None
    if not username or not password:
        raise RuntimeError("SLA_BASIC_AUTH_USER and SLA_BASIC_AUTH_PASSWORD must be set together")
    return username, password


def _install_basic_auth(app: FastAPI, *, username: str, password: str) -> None:
    @app.middleware("http")
    async def basic_auth_middleware(request: Request, call_next):
        if _is_public_path(request.url.path) or _has_valid_basic_auth(request, username, password):
            return await call_next(request)
        return PlainTextResponse(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="HSPACE SLA"'},
        )


def _is_public_path(path: str) -> bool:
    return path in {"/healthz", "/readyz"}


def _has_valid_basic_auth(request: Request, username: str, password: str) -> bool:
    authorization = request.headers.get("authorization", "")
    scheme, _, encoded_credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded_credentials:
        return False

    try:
        decoded_credentials = base64.b64decode(encoded_credentials, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False

    candidate_username, separator, candidate_password = decoded_credentials.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(candidate_username, username) and secrets.compare_digest(
        candidate_password,
        password,
    )


def _readiness_payload(
    store: SqliteStore,
    *,
    auth_enabled: bool,
    allowed_hosts: list[str],
    trusted_origins: set[str],
) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "ok" if ok else "fail", "detail": detail})

    deployment_config = _deployment_config_status(
        auth_enabled=auth_enabled,
        allowed_hosts=allowed_hosts,
        trusted_origins=trusted_origins,
    )
    add_check(
        "deployment_config",
        bool(deployment_config["ok"]),
        str(deployment_config["detail"]),
    )

    for name, path in (
        ("base_dir", store.base_dir),
        ("suites_dir", store.suites_dir),
        ("artifacts_dir", store.artifacts_dir),
    ):
        readable = path.exists() and path.is_dir() and os.access(path, os.R_OK)
        writable = path.exists() and path.is_dir() and os.access(path, os.W_OK)
        add_check(name, readable and writable, str(path))

    disk_free_status = _disk_free_status(store)
    if disk_free_status is not None:
        add_check(
            "disk_free",
            bool(disk_free_status["ok"]),
            str(disk_free_status["detail"]),
        )

    appium_status = _appium_readiness_status()
    if appium_status is not None:
        add_check(
            "appium_server",
            bool(appium_status["ok"]),
            str(appium_status["detail"]),
        )

    try:
        database_status = store.database_status()
        database_ok = (
            database_status["quick_check"] == "ok"
            and database_status["schema_version"] == database_status["expected_schema_version"]
            and database_status["journal_mode"] == "wal"
        )
        add_check(
            "database",
            database_ok,
            (
                f"{database_status['path']} "
                f"schema={database_status['schema_version']} "
                f"journal={database_status['journal_mode']} "
                f"quick_check={database_status['quick_check']}"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - readiness must report any storage failure.
        add_check("database", False, str(exc))

    status = "ok" if all(check["status"] == "ok" for check in checks) else "fail"
    return {"status": status, "checks": checks}


def _disk_free_status(store: SqliteStore) -> dict[str, object] | None:
    required_mb = _env_nonnegative_int("SLA_MIN_FREE_DISK_MB", 0)
    if required_mb <= 0:
        return None

    paths = _unique_disk_paths((store.base_dir, store.suites_dir, store.artifacts_dir, store.db_path.parent))
    details = []
    ok = True
    for path in paths:
        usage = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < required_mb:
            ok = False
        details.append(f"{path} free_mb={free_mb} required_mb={required_mb}")
    return {"ok": ok, "detail": "; ".join(details)}


def _appium_readiness_status() -> dict[str, object] | None:
    if not _env_bool("SLA_READY_CHECK_APPIUM", default=False):
        return None
    appium_url = os.getenv("APPIUM_URL", "http://127.0.0.1:4723")
    ready = is_appium_server_ready(appium_url)
    return {
        "ok": ready,
        "detail": f"{appium_url} status={'ready' if ready else 'unreachable'}",
    }


def _unique_disk_paths(paths: tuple[Path, ...]) -> list[Path]:
    unique: list[Path] = []
    seen = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return unique


def _deployment_config_status(
    *,
    auth_enabled: bool,
    allowed_hosts: list[str],
    trusted_origins: set[str],
) -> dict[str, object]:
    environment = os.getenv("SLA_ENV", "local")
    if environment != "production":
        return {
            "ok": True,
            "issues": [],
            "detail": f"environment={environment}; production checks skipped",
        }

    issues = []
    if not auth_enabled:
        issues.append("SLA_BASIC_AUTH_USER/SLA_BASIC_AUTH_PASSWORD")
    else:
        password_issue = _production_secret_issue(
            "SLA_BASIC_AUTH_PASSWORD",
            os.getenv("SLA_BASIC_AUTH_PASSWORD", ""),
            min_length=_MIN_PRODUCTION_PASSWORD_LENGTH,
        )
        if password_issue:
            issues.append(password_issue)

    csrf_issue = _production_secret_issue(
        "SLA_CSRF_SECRET",
        os.getenv("SLA_CSRF_SECRET", ""),
        min_length=_MIN_PRODUCTION_CSRF_SECRET_LENGTH,
    )
    if csrf_issue == "SLA_CSRF_SECRET":
        issues.append("SLA_CSRF_SECRET")
    elif csrf_issue:
        issues.append(csrf_issue)
    if not allowed_hosts:
        issues.append("SLA_ALLOWED_HOSTS")
    if not trusted_origins:
        issues.append("SLA_TRUSTED_ORIGINS")
    if os.getenv("SLA_BUILD_SHA", "").strip().lower() in {"", "local"}:
        issues.append("SLA_BUILD_SHA")

    return {
        "ok": not issues,
        "issues": issues,
        "detail": "production config ok" if not issues else f"issues: {', '.join(issues)}",
    }


def _production_secret_issue(name: str, value: str, *, min_length: int) -> str | None:
    secret = value.strip()
    if not secret:
        return name
    normalized = _normalized_secret_value(secret)
    if len(secret) < min_length or normalized in _PRODUCTION_PLACEHOLDER_SECRETS:
        return f"{name}_WEAK"
    return None


def _normalized_secret_value(value: str) -> str:
    parts: list[str] = []
    previous_dash = False
    for char in value.strip().lower():
        if char.isalnum():
            parts.append(char)
            previous_dash = False
        elif not previous_dash:
            parts.append("-")
            previous_dash = True
    return "".join(parts).strip("-")


def _version_payload(
    store: SqliteStore,
    *,
    auth_enabled: bool,
    allowed_hosts: list[str] | None = None,
    trusted_origins: set[str] | None = None,
    run_queue: RunQueue | None = None,
    recovered_incomplete_runs: int = 0,
) -> dict[str, object]:
    deployment_config = _deployment_config_status(
        auth_enabled=auth_enabled,
        allowed_hosts=allowed_hosts or [],
        trusted_origins=trusted_origins or set(),
    )
    queue_snapshot = run_queue.snapshot() if run_queue else {}
    return {
        "service": "sla-test-runner",
        "version": __version__,
        "build_sha": os.getenv("SLA_BUILD_SHA", ""),
        "environment": os.getenv("SLA_ENV", "local"),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "runtime": {
            "platform": sys.platform,
            "auth_enabled": auth_enabled,
            "allowed_hosts": allowed_hosts or [],
            "run_workers": run_queue.max_workers if run_queue else 0,
            "run_queue_limit": run_queue.queue_limit if run_queue else 0,
            "run_queue": queue_snapshot,
            "recovered_incomplete_runs": recovered_incomplete_runs,
            "deployment_config_ok": deployment_config["ok"],
            "deployment_issues": deployment_config["issues"],
            "base_dir": str(store.base_dir),
            "db_path": str(store.db_path),
        },
    }


def _metrics_payload(
    store: SqliteStore,
    run_queue: RunQueue,
    http_metrics: HttpMetrics | None = None,
) -> str:
    database_status = store.database_status()
    run_counts = store.run_counts()
    queue = run_queue.snapshot()
    http_series = http_metrics.snapshot() if http_metrics else []
    run_total = int(database_status["run_count"])
    suite_total = int(database_status["suite_count"])
    database_healthy = int(
        database_status["quick_check"] == "ok"
        and database_status["schema_version"] == database_status["expected_schema_version"]
        and database_status["journal_mode"] == "wal"
    )

    lines = [
        "# HELP sla_info Static build and runtime metadata for the SLA test runner.",
        "# TYPE sla_info gauge",
        (
            "sla_info"
            f'{{version="{_metric_label_value(__version__)}",'
            f'environment="{_metric_label_value(os.getenv("SLA_ENV", "local"))}",'
            f'build_sha="{_metric_label_value(os.getenv("SLA_BUILD_SHA", ""))}"}} 1'
        ),
        "# HELP sla_suites_total Number of registered test suites.",
        "# TYPE sla_suites_total gauge",
        f"sla_suites_total {suite_total}",
        "# HELP sla_runs_total Number of stored suite runs.",
        "# TYPE sla_runs_total gauge",
        f"sla_runs_total {run_total}",
        "# HELP sla_runs_by_status_total Number of stored suite runs by status.",
        "# TYPE sla_runs_by_status_total gauge",
    ]

    for status in ("QUEUED", "RUNNING", "PASS", "FAIL", "ERROR"):
        lines.append(f'sla_runs_by_status_total{{status="{status}"}} {int(run_counts.get(status, 0))}')

    lines.extend(
        [
            "# HELP sla_run_queue_limit Maximum number of running plus queued runs accepted by this process.",
            "# TYPE sla_run_queue_limit gauge",
            f"sla_run_queue_limit {queue['queue_limit']}",
            "# HELP sla_run_queue_available Available run queue slots in this process.",
            "# TYPE sla_run_queue_available gauge",
            f"sla_run_queue_available {queue['available']}",
            "# HELP sla_run_queue_reserved Running plus queued runs in this process.",
            "# TYPE sla_run_queue_reserved gauge",
            f"sla_run_queue_reserved {queue['reserved']}",
            "# HELP sla_run_queue_running Runs currently executing in this process.",
            "# TYPE sla_run_queue_running gauge",
            f"sla_run_queue_running {queue['running']}",
            "# HELP sla_run_queue_queued Runs accepted but not yet executing in this process.",
            "# TYPE sla_run_queue_queued gauge",
            f"sla_run_queue_queued {queue['queued']}",
            "# HELP sla_run_queue_accepted_total Runs accepted into this process queue since startup.",
            "# TYPE sla_run_queue_accepted_total counter",
            f"sla_run_queue_accepted_total {queue['accepted_total']}",
            "# HELP sla_run_queue_completed_total Runs completed by this process queue since startup.",
            "# TYPE sla_run_queue_completed_total counter",
            f"sla_run_queue_completed_total {queue['completed_total']}",
            "# HELP sla_run_queue_rejected_total Runs rejected because this process queue was full since startup.",
            "# TYPE sla_run_queue_rejected_total counter",
            f"sla_run_queue_rejected_total {queue['rejected_total']}",
            "# HELP sla_http_requests_total Total HTTP requests by method, route, and status.",
            "# TYPE sla_http_requests_total counter",
        ]
    )

    for item in http_series:
        labels = (
            f'method="{_metric_label_value(item["method"])}",'
            f'path="{_metric_label_value(item["path"])}",'
            f'status="{_metric_label_value(item["status"])}"'
        )
        lines.append(f"sla_http_requests_total{{{labels}}} {int(item['count'])}")

    lines.extend(
        [
            "# HELP sla_http_request_duration_seconds HTTP request duration by method, route, and status.",
            "# TYPE sla_http_request_duration_seconds summary",
        ]
    )

    for item in http_series:
        labels = (
            f'method="{_metric_label_value(item["method"])}",'
            f'path="{_metric_label_value(item["path"])}",'
            f'status="{_metric_label_value(item["status"])}"'
        )
        lines.append(f"sla_http_request_duration_seconds_count{{{labels}}} {int(item['count'])}")
        lines.append(
            "sla_http_request_duration_seconds_sum"
            f"{{{labels}}} {float(item['duration_seconds_sum']):.6f}"
        )

    lines.extend(
        [
            "# HELP sla_database_healthy Whether SQLite schema, WAL, and quick_check are healthy.",
            "# TYPE sla_database_healthy gauge",
            f"sla_database_healthy {database_healthy}",
            "# HELP sla_database_schema_version Current SQLite schema version.",
            "# TYPE sla_database_schema_version gauge",
            f"sla_database_schema_version {int(database_status['schema_version'])}",
            "# HELP sla_database_expected_schema_version Expected SQLite schema version.",
            "# TYPE sla_database_expected_schema_version gauge",
            f"sla_database_expected_schema_version {int(database_status['expected_schema_version'])}",
        ]
    )
    return "\n".join(lines) + "\n"


def _metric_label_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _maintenance_context(store: SqliteStore, request: Request, *, auth_enabled: bool) -> dict[str, object]:
    artifact_bytes = _directory_size(store.artifacts_dir)
    db_bytes = store.db_path.stat().st_size if store.db_path.exists() else 0
    return {
        "auth_enabled": auth_enabled,
        "base_dir": str(store.base_dir),
        "db_path": str(store.db_path),
        "db_size": _format_bytes(db_bytes),
        "artifact_dir": str(store.artifacts_dir),
        "artifact_size": _format_bytes(artifact_bytes),
        "run_count": store.run_count(),
        "suite_count": len(store.list_suites()),
        "retention_keep_last": _env_int("SLA_RETENTION_KEEP_LAST", 100),
        "retention_days": _env_int("SLA_RETENTION_DAYS", 30),
        "notice": _maintenance_notice(request),
    }


def _maintenance_notice(request: Request) -> str:
    if request.query_params.get("maintenance") != "pruned":
        return ""
    deleted_runs = request.query_params.get("deleted_runs", "0")
    deleted_artifacts = request.query_params.get("deleted_artifacts", "0")
    return f"실행 {deleted_runs}개와 아티팩트 디렉터리 {deleted_artifacts}개를 정리했습니다."


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    resolved_root = path.resolve()
    for child in path.rglob("*"):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            resolved_child = child.resolve()
            resolved_child.relative_to(resolved_root)
            total += resolved_child.stat().st_size
        except (OSError, ValueError):
            continue
    return total


def _backup_zip_response(store: SqliteStore) -> Response:
    generated_at = datetime.now(UTC)
    payload = _backup_zip_bytes(store, generated_at=generated_at)
    filename = f"sla-backup-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.zip"
    return Response(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _backup_zip_bytes(store: SqliteStore, *, generated_at: datetime) -> bytes:
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        db_backup_path = store.backup_database(Path(tmp) / "sla_app.db")
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.write(db_backup_path, "database/sla_app.db")
            suite_files, skipped_suite_files = _write_directory_to_zip(archive, store.suites_dir, "suites")
            artifact_files, skipped_artifact_files = _write_directory_to_zip(
                archive,
                store.artifacts_dir,
                "artifacts",
            )
            manifest = {
                "backup_version": 1,
                "generated_at": generated_at.isoformat(),
                "base_dir": str(store.base_dir),
                "db_path": str(store.db_path),
                "suite_count": len(store.list_suites()),
                "run_count": store.run_count(),
                "included_suite_files": suite_files,
                "included_artifact_files": artifact_files,
                "skipped_unsafe_files": skipped_suite_files + skipped_artifact_files,
            }
            archive.writestr("manifest.json", _json_dumps(manifest))
    return buffer.getvalue()


def _write_directory_to_zip(archive: zipfile.ZipFile, root: Path, prefix: str) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    included = 0
    skipped = 0
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            if path.is_symlink():
                skipped += 1
            continue
        try:
            resolved_path = path.resolve()
            relative_path = resolved_path.relative_to(resolved_root)
        except (OSError, ValueError):
            skipped += 1
            continue
        archive.write(resolved_path, f"{prefix}/{relative_path.as_posix()}")
        included += 1
    return included, skipped


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_report_payload(store: SqliteStore, run_id: str) -> dict[str, object] | None:
    detail = store.get_run_detail(run_id)
    if detail is None:
        return None
    comparison = _run_comparison(store, detail)
    previous_detail = store.get_run_detail(str(comparison["run_id"])) if comparison else None
    return {
        "report_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "run": detail,
        "insights": _run_insights(detail),
        "comparison": comparison,
        "metric_summary": _run_metric_summary(detail, previous_detail),
        "run_history": _run_history(store, detail),
        "artifacts": _run_artifacts(store, detail),
    }


def _run_artifacts(store: SqliteStore, run: dict) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []
    for scenario in run.get("scenarios", []) or []:
        scenario_name = str(scenario.get("name") or "")
        for step in scenario.get("step_results", []) or []:
            screenshot_path = step.get("screenshot_path")
            url = _artifact_url(store, screenshot_path)
            if not url:
                continue
            artifacts.append(
                {
                    "scenario": scenario_name,
                    "step_index": step.get("index"),
                    "action": step.get("action"),
                    "type": "screenshot",
                    "path": screenshot_path,
                    "url": url,
                }
            )
    return artifacts


def _run_insights(run: dict) -> list[dict[str, str]]:
    status = str(run.get("status") or "")
    if status == "QUEUED":
        return [
            {
                "level": "neutral",
                "title": "실행 대기 중",
                "detail": "실행 작업자가 순서대로 처리할 때까지 대기하고 있습니다.",
            }
        ]
    if status == "RUNNING":
        return [
            {
                "level": "warn",
                "title": "실행 중",
                "detail": "Appium 실행이 백그라운드에서 진행 중입니다. 완료되면 이 화면에 결과가 반영됩니다.",
            }
        ]
    if status == "ERROR":
        return [
            {
                "level": "fail",
                "title": "실행 작업자 오류",
                "detail": "백그라운드 작업자가 실행을 완료하지 못했습니다. 실행 기록의 메시지와 서버 로그를 확인하세요.",
            }
        ]
    if run.get("status") == "PASS":
        return [
            {
                "level": "ok",
                "title": "SLA 통과",
                "detail": "이번 실행은 모든 시나리오와 SLA 기준을 통과했습니다.",
            }
        ]

    insights: list[dict[str, str]] = []
    for reason in run.get("reasons", []):
        insights.append(_sla_reason_insight(str(reason)))

    for scenario in run.get("scenarios", []):
        scenario_name = str(scenario.get("name") or "시나리오")
        for step in scenario.get("step_results", []):
            if step.get("success"):
                continue
            category = str(step.get("failure_category") or _fallback_failure_category(step))
            action = str(step.get("action") or "동작")
            insights.append(
                {
                    "level": "fail",
                    "title": f"{scenario_name}: {category}",
                    "detail": f"{_step_action_label(action)} 단계에서 실패했습니다. {_human_step_message(step)}",
                }
            )
            if len(insights) >= 6:
                return insights
    if not insights:
        insights.append(
            {
                "level": "fail",
                "title": "실패 원인 확인 필요",
                "detail": "저장된 실행 로그에 구체적인 실패 메시지가 없습니다.",
            }
        )
    return insights


def _run_comparison(store: SqliteStore, run: dict) -> dict[str, str | int] | None:
    if run.get("status") not in {"PASS", "FAIL"}:
        return None
    suite_id = run.get("suite_id")
    run_id = run.get("run_id")
    started_at = str(run.get("started_at") or "")
    previous = None
    for candidate in store.list_runs_for_suite(str(suite_id), limit=100):
        if candidate.run_id == run_id:
            continue
        if not started_at or candidate.started_at < started_at:
            previous = candidate
            break
    if previous is None:
        return None

    duration_ms = int(run.get("duration_ms") or 0)
    delta_ms = duration_ms - previous.duration_ms
    if delta_ms > 0:
        duration_label = f"{delta_ms} ms 느려졌습니다"
    elif delta_ms < 0:
        duration_label = f"{abs(delta_ms)} ms 빨라졌습니다"
    else:
        duration_label = "실행 시간이 같습니다"
    return {
        "run_id": previous.run_id,
        "status": previous.status,
        "duration_ms": previous.duration_ms,
        "delta_ms": delta_ms,
        "duration_label": duration_label,
    }


def _run_metric_summary(run: dict, previous_run: dict | None = None) -> list[dict[str, str]]:
    metrics = _run_metric_values(run)
    previous_metrics = _run_metric_values(previous_run or {})
    items: list[dict[str, str]] = []
    for name in _ordered_metric_names(metrics):
        value = metrics[name]
        previous_value = previous_metrics.get(name)
        delta = value - previous_value if previous_value is not None else None
        items.append(
            {
                "name": name,
                "label": _metric_label(name),
                "value": _format_metric_value(name, value),
                "delta": _format_metric_delta(name, delta),
                "level": _metric_delta_level(delta),
            }
        )
    return items


def _run_metric_values(run: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for scenario in run.get("scenarios", []) or []:
        raw_metrics = scenario.get("metrics", {}) if isinstance(scenario, dict) else {}
        if not isinstance(raw_metrics, dict):
            continue
        for name, raw_value in raw_metrics.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            key = str(name)
            values[key] = max(values[key], value) if key in values else value
    return values


def _ordered_metric_names(metrics: dict[str, float]) -> list[str]:
    preferred = [
        "launch_time_ms",
        "appium_new_session_ms",
        "appium_command_max_ms",
        "appium_command_avg_ms",
        "memory_mb",
        "cpu_percent",
        "logcat_error_count",
        "appium_command_count",
    ]
    return [name for name in preferred if name in metrics] + sorted(
        name for name in metrics if name not in preferred
    )


def _metric_label(name: str) -> str:
    return {
        "launch_time_ms": "실행 지연",
        "appium_new_session_ms": "세션 생성",
        "appium_command_max_ms": "명령 최대 지연",
        "appium_command_avg_ms": "명령 평균 지연",
        "appium_command_count": "명령 수",
        "memory_mb": "메모리",
        "cpu_percent": "CPU",
        "logcat_error_count": "로그 에러",
    }.get(name, name)


def _format_metric_value(name: str, value: float) -> str:
    if name.endswith("_ms"):
        return f"{value:.0f} ms"
    if name == "memory_mb":
        return f"{value:.1f} MB"
    if name == "cpu_percent":
        return f"{value:.1f}%"
    if name.endswith("_count"):
        return f"{value:.0f}"
    return f"{value:g}"


def _format_metric_delta(name: str, delta: float | None) -> str:
    if delta is None:
        return "이전 값 없음"
    if abs(delta) < 0.005:
        return "변화 없음"
    direction = "증가" if delta > 0 else "감소"
    return f"{_format_metric_value(name, abs(delta))} {direction}"


def _metric_delta_level(delta: float | None) -> str:
    if delta is None or abs(delta) < 0.005:
        return "neutral"
    return "warn" if delta > 0 else "ok"


def _run_history(store: SqliteStore, run: dict) -> list[dict[str, str | int | bool]]:
    suite_id = str(run.get("suite_id") or "")
    run_id = str(run.get("run_id") or "")
    summaries = store.list_runs_for_suite(suite_id, limit=6)
    return _run_history_from_summaries(summaries, run_id)


def _run_history_from_summaries(summaries, current_run_id: str) -> list[dict[str, str | int | bool]]:
    if not summaries:
        return []
    max_duration = max((summary.duration_ms for summary in summaries), default=1) or 1
    history = []
    for summary in reversed(summaries):
        history.append(
            {
                "run_id": summary.run_id,
                "status": summary.status,
                "started_at": summary.started_at,
                "duration_ms": summary.duration_ms,
                "bar_percent": max(6, int(summary.duration_ms / max_duration * 100)),
                "is_current": summary.run_id == current_run_id,
            }
        )
    return history


def _suite_signals(runs) -> dict[str, object]:
    terminal_runs = [run for run in runs if run.status in {"PASS", "FAIL"}]
    total = len(terminal_runs)
    pass_count = sum(1 for run in terminal_runs if run.status == "PASS")
    fail_count = sum(1 for run in terminal_runs if run.status == "FAIL")
    pass_rate = int(round(pass_count / total * 100)) if total else 0
    avg_duration = int(round(sum(run.duration_ms for run in terminal_runs) / total)) if total else 0
    latest = runs[0] if runs else None
    latest_failure = next((run for run in terminal_runs if run.status == "FAIL"), None)
    slowest = max(terminal_runs, key=lambda run: run.duration_ms, default=None)
    return {
        "total": len(runs),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "avg_duration_ms": avg_duration,
        "latest": latest,
        "latest_failure": latest_failure,
        "slowest": slowest,
    }


def _dashboard_signals(runs) -> dict[str, object]:
    terminal_runs = [run for run in runs if run.status in {"PASS", "FAIL"}]
    total = len(terminal_runs)
    pass_count = sum(1 for run in terminal_runs if run.status == "PASS")
    fail_count = sum(1 for run in terminal_runs if run.status == "FAIL")
    pass_rate = int(round(pass_count / total * 100)) if total else 0
    latest_failure = next((run for run in terminal_runs if run.status == "FAIL"), None)
    slowest = max(terminal_runs, key=lambda run: run.duration_ms, default=None)
    return {
        "total": len(runs),
        "pass_rate": pass_rate,
        "fail_count": fail_count,
        "latest_failure": latest_failure,
        "slowest": slowest,
    }


def _sla_reason_insight(reason: str) -> dict[str, str]:
    if reason == "scenario execution failed":
        return {
            "level": "fail",
            "title": "시나리오 실행 실패",
            "detail": "하나 이상의 단계가 실패해서 시나리오가 완료되지 않았습니다.",
        }
    if reason.startswith("duration_ms"):
        return {
            "level": "fail",
            "title": "실행 시간 초과",
            "detail": f"SLA 최대 실행 시간을 넘었습니다. 원문: {reason}",
        }
    if reason.startswith("assertion_failures"):
        return {
            "level": "fail",
            "title": "검증 실패 초과",
            "detail": f"허용된 검증 실패 수보다 많이 실패했습니다. 원문: {reason}",
        }
    if reason.startswith("assertion_count"):
        return {
            "level": "fail",
            "title": "필수 검증 부족",
            "detail": f"요구한 검증 개수를 채우지 못했습니다. 원문: {reason}",
        }
    if reason.startswith("metric "):
        return {
            "level": "fail",
            "title": "지표 기준 위반",
            "detail": f"수집된 기술 지표가 기준을 만족하지 못했습니다. 원문: {reason}",
        }
    if reason.startswith("metric_violations"):
        return {
            "level": "fail",
            "title": "지표 위반 초과",
            "detail": f"허용된 지표 위반 수보다 많이 실패했습니다. 원문: {reason}",
        }
    return {"level": "fail", "title": "SLA 위반", "detail": reason}


def _fallback_failure_category(step: dict) -> str:
    action = str(step.get("action") or "")
    message = str(step.get("message") or "").lower()
    if action == "launch_app" or "launcher exited" in message or "appium" in message:
        return "환경/실행"
    if action == "metric_check":
        return "지표 위반"
    if "element not found" in message or action == "assert_exists":
        return "요소 찾기 실패"
    if action in {
        "assert_not_exists",
        "assert_visible",
        "assert_enabled",
        "assert_attribute",
        "assert_current_package",
        "assert_current_activity",
    }:
        return "검증 실패"
    if "text not found" in message or action == "assert_text":
        return "텍스트 검증 실패"
    if "text still present" in message or action == "assert_not_text":
        return "텍스트 검증 실패"
    return "실행 오류"


def _human_step_message(step: dict) -> str:
    action = str(step.get("action") or "")
    message = str(step.get("message") or "").strip()
    normalized = message.lower()
    if "launcher exited" in normalized:
        return "런처가 종료되었습니다. 설정의 환경 진단에서 Android SDK, Node.js, Appium 패키지를 먼저 확인하세요."
    if "element not found" in normalized:
        return "요소를 찾지 못했습니다. 화면 요소 검색에서 다시 선택하거나 대기 시간을 늘려보세요."
    if "element still present" in normalized:
        return "없어져야 할 요소가 아직 화면에 있습니다. 이전 단계 완료 여부나 대기 시간을 확인하세요."
    if "text not found" in normalized:
        return "텍스트를 찾지 못했습니다. 앱 화면 문구가 바뀌었거나 실행 타이밍이 빠를 수 있습니다."
    if "text still present" in normalized:
        return "보이면 안 되는 텍스트가 아직 남아 있습니다. 에러 문구 또는 로딩 상태를 확인하세요."
    if "not visible" in normalized:
        return "요소가 화면에 표시되지 않았습니다. 스크롤 위치나 조건을 확인하세요."
    if "not enabled" in normalized:
        return "요소가 비활성 상태입니다. 이전 단계가 완료됐는지 확인하세요."
    if "attribute" in normalized and "expected" in normalized:
        return "요소 속성이 기대값과 다릅니다. 앱 상태 또는 selector가 맞는지 확인하세요."
    if "package expected" in normalized:
        return "현재 앱 package가 기대와 다릅니다. 외부 앱이나 로그인 화면으로 이탈했는지 확인하세요."
    if "activity expected" in normalized:
        return "현재 화면 activity가 기대와 다릅니다. 화면 전환 조건과 대기 시간을 확인하세요."
    if action == "metric_check":
        return "수집된 지표가 설정한 최소/최대 기준을 벗어났습니다."
    if message:
        return message
    return "상세 메시지가 없습니다."


def _step_action_label(action: str) -> str:
    return {
        "launch_app": "앱 실행",
        "terminate_app": "앱 종료",
        "activate_app": "앱 활성화",
        "background_app": "백그라운드",
        "tap": "탭",
        "input": "입력",
        "back": "뒤로가기",
        "swipe": "스와이프",
        "scroll": "스크롤",
        "scroll_to_text": "텍스트까지 스크롤",
        "wait": "대기",
        "assert_text": "텍스트 검증",
        "assert_not_text": "텍스트 미노출 검증",
        "assert_exists": "요소 존재 검증",
        "assert_not_exists": "요소 미존재 검증",
        "assert_visible": "표시 검증",
        "assert_enabled": "활성화 검증",
        "assert_attribute": "속성 검증",
        "assert_current_package": "현재 패키지 검증",
        "assert_current_activity": "현재 화면 검증",
        "screenshot": "스크린샷",
        "collect_metrics": "지표 수집",
        "metric_check": "지표 확인",
    }.get(action, action)


def _helper_url_if_available(store: SqliteStore, suite_id: str) -> str | None:
    try:
        suite = store.load_suite(suite_id)
    except KeyError:
        return None
    helper_available, _helper_reasons = _builder_compatibility(suite)
    return f"/suites/{suite_id}/edit/helper" if helper_available else None


def _installed_apps_payload() -> dict[str, object]:
    config = _android_discovery_config()
    sdk_root = resolve_sdk_root(config.android_sdk_root)
    adb_hint = config.adb_path or sdk_tool_path(
        sdk_root,
        "platform-tools",
        platform_executable_name("adb"),
    )
    adb_path = resolve_executable(adb_hint, platform_executable_name("adb"))
    serial = ensure_emulator(config, adb_path)
    apps = list_launchable_apps(adb_path, serial)
    return {
        "device": serial,
        "apps": [app.to_dict() for app in apps],
    }


def _app_target_from_scan_request(
    *,
    target_mode: str,
    apk: str,
    app_package: str,
    app_activity: str,
    app_wait_activity: str,
    app_wait_package: str,
    no_reset: bool,
) -> AppTarget:
    if target_mode == "installed":
        if not app_package or not app_activity:
            raise ValueError("먼저 설치된 앱을 선택하거나 package/activity를 입력하세요.")
        return AppTarget(
            platform="android",
            app_package=app_package.strip(),
            app_activity=app_activity.strip(),
            app_wait_activity="*",
            app_wait_package="*",
            no_reset=no_reset,
        )

    if not apk:
        raise ValueError("화면을 스캔하기 전에 APK 경로를 입력하세요.")
    return AppTarget(platform="android", apk=apk.strip(), no_reset=no_reset)


def _inspect_app_target_elements(
    app_target: AppTarget,
    source_path: Path | None = None,
    mode: str = "standard",
) -> dict[str, object]:
    suite = TestSuite(
        name="화면 요소 스캔",
        app=app_target,
        scenarios=[Scenario(name="scan", steps=[ActionStep(action="launch_app")])],
        source_path=source_path,
    )
    adapter = AndroidAppiumAdapter.from_suite(suite)
    try:
        return {"elements": adapter.inspect_elements(_element_scan_mode(mode))}
    finally:
        adapter.close()


def _element_scan_mode(mode: str) -> str:
    return "advanced" if mode == "advanced" else "standard"


def _android_discovery_config() -> LaunchConfig:
    sdk_root_default = os.getenv("ANDROID_SDK_ROOT") or os.getenv("ANDROID_HOME") or str(default_sdk_root())
    return LaunchConfig(
        appium_url=os.getenv("APPIUM_URL", "http://127.0.0.1:4723"),
        start_appium=False,
        keep_appium_running=False,
        node_path=os.getenv("APPIUM_NODE_PATH"),
        npm_path=os.getenv("APPIUM_NPM_PATH"),
        appium_main_script=os.getenv("APPIUM_MAIN_SCRIPT"),
        avd=os.getenv("ANDROID_AVD"),
        serial=os.getenv("ANDROID_SERIAL"),
        emulator_path=os.getenv("ANDROID_EMULATOR_PATH"),
        android_sdk_root=sdk_root_default,
        adb_path=os.getenv("ANDROID_ADB_PATH"),
        device_name=os.getenv("ANDROID_DEVICE_NAME", "Android Emulator"),
        apk=None,
        app_package=None,
        app_activity=None,
        app_wait_activity=None,
        app_wait_package=None,
        no_reset=True,
        boot_timeout=int(os.getenv("ANDROID_BOOT_TIMEOUT", "240")),
        server_timeout=int(os.getenv("APPIUM_SERVER_TIMEOUT", "45")),
        launch_wait=0,
        emulator_args=tuple(filter(None, os.getenv("ANDROID_EMULATOR_ARGS", "").split())),
    )


def _system_exit_message(exc: SystemExit) -> str:
    if isinstance(exc.code, int):
        return f"런처가 코드 {exc.code}로 종료되었습니다"
    if exc.code:
        return str(exc.code)
    return "런처가 종료되었습니다"


def _friendly_appium_error(exc: Exception) -> str:
    message = str(exc).strip()
    if "Stacktrace:" in message:
        message = message.split("Stacktrace:", 1)[0].strip()
    if "Original error:" in message and "Cannot start" in message:
        return (
            "선택한 앱을 시작하지 못했습니다. 앱이 다른 activity/package 화면으로 열릴 수 있습니다. "
            "대기 Activity와 대기 Package를 *로 두거나 다른 실행 Activity를 선택하세요. "
            f"상세: {message}"
        )
    return message or exc.__class__.__name__


def _import_existing_suites(store: SqliteStore) -> None:
    for path in sorted(store.suites_dir.glob("*.yaml")):
        try:
            suite = suite_from_yaml_text(path.read_text(encoding="utf-8"), source_path=path)
            store.register_suite_file(path.stem, suite, path)
        except SuiteValidationError:
            continue


def _default_builder_state() -> dict[str, object]:
    return {
        "suite_name": "Android 기본 테스트",
        "target_mode": "apk",
        "apk": "test-apk/build/hspace-test-app-debug.apk",
        "app_package": "",
        "app_activity": "",
        "app_wait_activity": "",
        "app_wait_package": "",
        "no_reset": False,
        "max_duration_ms": "30000",
        "max_assertion_failures": "0",
        "max_metric_violations": "0",
        "required_assertions": "",
        "memory_mb_max": "",
        "launch_time_ms_max": "",
        "appium_new_session_ms_max": "",
        "appium_command_max_ms_max": "",
        "appium_command_avg_ms_max": "",
        "cpu_percent_max": "",
        "logcat_error_count_max": "",
        "scenario_name": "실행 후 캡처",
        "steps": [
            {"action": "launch_app"},
            {"action": "wait", "timeout_ms": "1000"},
            {"action": "screenshot", "name": "launch"},
        ],
    }


def _builder_state_from_suite(suite: TestSuite) -> dict[str, object]:
    scenario = suite.scenarios[0]
    target_mode = "installed" if suite.app.app_package and suite.app.app_activity else "apk"
    memory_limit = suite.thresholds.metrics.get("memory_mb")
    launch_time_limit = suite.thresholds.metrics.get("launch_time_ms")
    appium_new_session_limit = suite.thresholds.metrics.get("appium_new_session_ms")
    appium_command_max_limit = suite.thresholds.metrics.get("appium_command_max_ms")
    appium_command_avg_limit = suite.thresholds.metrics.get("appium_command_avg_ms")
    cpu_limit = suite.thresholds.metrics.get("cpu_percent")
    logcat_limit = suite.thresholds.metrics.get("logcat_error_count")
    return {
        "suite_name": suite.name,
        "target_mode": target_mode,
        "apk": suite.app.apk or "",
        "app_package": suite.app.app_package or "",
        "app_activity": suite.app.app_activity or "",
        "app_wait_activity": suite.app.app_wait_activity or "",
        "app_wait_package": suite.app.app_wait_package or "",
        "no_reset": suite.app.no_reset,
        "max_duration_ms": _text_or_empty(suite.thresholds.max_duration_ms),
        "max_assertion_failures": str(suite.thresholds.max_assertion_failures),
        "max_metric_violations": str(suite.thresholds.max_metric_violations),
        "required_assertions": _text_or_empty(suite.thresholds.required_assertions),
        "memory_mb_max": _text_or_empty(memory_limit.max if memory_limit else None),
        "launch_time_ms_max": _text_or_empty(launch_time_limit.max if launch_time_limit else None),
        "appium_new_session_ms_max": _text_or_empty(
            appium_new_session_limit.max if appium_new_session_limit else None
        ),
        "appium_command_max_ms_max": _text_or_empty(
            appium_command_max_limit.max if appium_command_max_limit else None
        ),
        "appium_command_avg_ms_max": _text_or_empty(
            appium_command_avg_limit.max if appium_command_avg_limit else None
        ),
        "cpu_percent_max": _text_or_empty(cpu_limit.max if cpu_limit else None),
        "logcat_error_count_max": _text_or_empty(logcat_limit.max if logcat_limit else None),
        "scenario_name": scenario.name,
        "steps": [_builder_step_from_model(step) for step in scenario.steps],
    }


def _builder_step_from_model(step: ActionStep) -> dict[str, str]:
    return {
        "action": step.action,
        "selector": step.selector or "",
        "text": step.text or "",
        "value": _text_or_empty(step.value),
        "timeout_ms": _text_or_empty(step.timeout_ms),
        "name": step.name or "",
        "metric": step.metric or "",
        "direction": step.direction or "",
        "percent": _text_or_empty(step.percent),
        "attribute": step.attribute or "",
        "package": step.package or "",
        "activity": step.activity or "",
        "min": _text_or_empty(step.min),
        "max": _text_or_empty(step.max),
    }


def _builder_compatibility(suite: TestSuite) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(suite.scenarios) != 1:
        reasons.append("쉬운 편집기는 스위트당 시나리오 1개만 지원합니다.")
    elif suite.scenarios[0].thresholds is not None:
        reasons.append("시나리오별 SLA 기준은 YAML 편집이 필요합니다.")

    metric_names = set(suite.thresholds.metrics)
    supported_metric_names = {
        "memory_mb",
        "launch_time_ms",
        "appium_new_session_ms",
        "appium_command_max_ms",
        "appium_command_avg_ms",
        "cpu_percent",
        "logcat_error_count",
    }
    if metric_names - supported_metric_names:
        reasons.append("커스텀 스위트 지표 기준은 YAML 편집이 필요합니다.")
    for name in sorted(metric_names & supported_metric_names):
        limit = suite.thresholds.metrics[name]
        if limit.min is not None:
            reasons.append(f"{name} 최소 기준은 YAML 편집이 필요합니다.")

    supported_step_keys = {
        "action",
        "selector",
        "text",
        "value",
        "timeout_ms",
        "name",
        "metric",
        "direction",
        "percent",
        "attribute",
        "package",
        "activity",
        "min",
        "max",
    }
    for scenario in suite.scenarios:
        for index, step in enumerate(scenario.steps, start=1):
            extra_keys = set(step.raw) - supported_step_keys
            if extra_keys:
                keys = ", ".join(sorted(extra_keys))
                reasons.append(f"{index}번 스텝에 고급 YAML 필드가 있습니다: {keys}.")
                break
        if reasons:
            break

    return not reasons, reasons


def _builder_state_from_form(form) -> dict[str, object]:
    actions = _form_list(form, "step_action")
    steps: list[dict[str, str]] = []
    for index, action in enumerate(actions):
        action = action.strip()
        if not action:
            continue
        steps.append(
            {
                "action": action,
                "selector": _indexed_form_value(form, "step_selector", index),
                "text": _indexed_form_value(form, "step_text", index),
                "value": _indexed_form_value(form, "step_value", index),
                "timeout_ms": _indexed_form_value(form, "step_timeout_ms", index),
                "name": _indexed_form_value(form, "step_name", index),
                "metric": _indexed_form_value(form, "step_metric", index),
                "direction": _indexed_form_value(form, "step_direction", index),
                "percent": _indexed_form_value(form, "step_percent", index),
                "attribute": _indexed_form_value(form, "step_attribute", index),
                "package": _indexed_form_value(form, "step_package", index),
                "activity": _indexed_form_value(form, "step_activity", index),
                "min": _indexed_form_value(form, "step_min", index),
                "max": _indexed_form_value(form, "step_max", index),
            }
        )

    return {
        "suite_name": _form_value(form, "suite_name"),
        "target_mode": _form_value(form, "target_mode", "apk"),
        "apk": _form_value(form, "apk"),
        "app_package": _form_value(form, "app_package"),
        "app_activity": _form_value(form, "app_activity"),
        "app_wait_activity": _form_value(form, "app_wait_activity"),
        "app_wait_package": _form_value(form, "app_wait_package"),
        "no_reset": form.get("no_reset") == "true",
        "max_duration_ms": _form_value(form, "max_duration_ms"),
        "max_assertion_failures": _form_value(form, "max_assertion_failures", "0"),
        "max_metric_violations": _form_value(form, "max_metric_violations", "0"),
        "required_assertions": _form_value(form, "required_assertions"),
        "memory_mb_max": _form_value(form, "memory_mb_max"),
        "launch_time_ms_max": _form_value(form, "launch_time_ms_max"),
        "appium_new_session_ms_max": _form_value(form, "appium_new_session_ms_max"),
        "appium_command_max_ms_max": _form_value(form, "appium_command_max_ms_max"),
        "appium_command_avg_ms_max": _form_value(form, "appium_command_avg_ms_max"),
        "cpu_percent_max": _form_value(form, "cpu_percent_max"),
        "logcat_error_count_max": _form_value(form, "logcat_error_count_max"),
        "scenario_name": _form_value(form, "scenario_name"),
        "steps": steps,
    }


def _builder_state_to_yaml(builder: dict[str, object]) -> str:
    target_mode = str(builder.get("target_mode") or "apk")
    app_data = {"platform": "android"}
    if target_mode == "installed":
        app_data["app_package"] = str(builder.get("app_package") or "")
        app_data["app_activity"] = str(builder.get("app_activity") or "")
        if builder.get("app_wait_activity"):
            app_data["app_wait_activity"] = str(builder["app_wait_activity"])
        if builder.get("app_wait_package"):
            app_data["app_wait_package"] = str(builder["app_wait_package"])
        if builder.get("no_reset"):
            app_data["no_reset"] = True
    else:
        app_data["apk"] = str(builder.get("apk") or "")

    metrics = {}
    _set_metric_max(metrics, "memory_mb", builder.get("memory_mb_max"))
    _set_metric_max(metrics, "launch_time_ms", builder.get("launch_time_ms_max"))
    _set_metric_max(metrics, "appium_new_session_ms", builder.get("appium_new_session_ms_max"))
    _set_metric_max(metrics, "appium_command_max_ms", builder.get("appium_command_max_ms_max"))
    _set_metric_max(metrics, "appium_command_avg_ms", builder.get("appium_command_avg_ms_max"))
    _set_metric_max(metrics, "cpu_percent", builder.get("cpu_percent_max"))
    _set_metric_max(metrics, "logcat_error_count", builder.get("logcat_error_count_max"))

    thresholds = SlaThresholds(
        max_duration_ms=_optional_int_text(builder.get("max_duration_ms")),
        max_assertion_failures=_int_text(builder.get("max_assertion_failures"), 0),
        max_metric_violations=_int_text(builder.get("max_metric_violations"), 0),
        required_assertions=_int_text(builder.get("required_assertions"), 0),
        metrics=metrics,
    )
    steps = [
        ActionStep.from_mapping(_step_mapping_from_builder(step))
        for step in builder.get("steps", [])
        if isinstance(step, dict)
    ]
    suite = TestSuite(
        name=str(builder.get("suite_name") or "").strip(),
        app=AppTarget.from_mapping(app_data),
        thresholds=thresholds,
        scenarios=[
            Scenario(
                name=str(builder.get("scenario_name") or "").strip(),
                steps=steps,
            )
        ],
    )
    return suite_to_yaml(suite)


def _set_metric_max(metrics: dict[str, MetricLimit], name: str, value: object) -> None:
    parsed = _optional_float_text(value)
    if parsed is not None:
        metrics[name] = MetricLimit(max=parsed)


def _step_mapping_from_builder(step: dict[str, str]) -> dict[str, object]:
    action = str(step.get("action") or "")
    mapping: dict[str, object] = {"action": action}
    if action in {
        "tap",
        "assert_exists",
        "assert_not_exists",
        "assert_visible",
        "assert_enabled",
    }:
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "text", step.get("text"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action in {"terminate_app", "activate_app"}:
        _set_if_present(mapping, "package", step.get("package"))
    elif action == "background_app":
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "input":
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "value", step.get("value"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action in {"swipe", "scroll"}:
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "text", step.get("text"))
        _set_if_present(mapping, "direction", step.get("direction"))
        _set_optional_float(mapping, "percent", step.get("percent"))
    elif action == "scroll_to_text":
        _set_if_present(mapping, "text", step.get("text"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "wait":
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action in {"assert_text", "assert_not_text"}:
        _set_if_present(mapping, "text", step.get("text"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "assert_attribute":
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "text", step.get("text"))
        _set_if_present(mapping, "attribute", step.get("attribute"))
        _set_if_present(mapping, "value", step.get("value"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "assert_current_package":
        _set_if_present(mapping, "package", step.get("package"))
    elif action == "assert_current_activity":
        _set_if_present(mapping, "activity", step.get("activity"))
    elif action == "screenshot":
        _set_if_present(mapping, "name", step.get("name"))
    elif action == "metric_check":
        _set_if_present(mapping, "metric", step.get("metric"))
        _set_optional_float(mapping, "min", step.get("min"))
        _set_optional_float(mapping, "max", step.get("max"))
    return mapping


def _form_value(form, key: str, default: str = "") -> str:
    value = form.get(key, default)
    return str(value).strip() if value is not None else default


def _form_list(form, key: str) -> list[str]:
    return [str(value) for value in form.getlist(key)]


def _indexed_form_value(form, key: str, index: int) -> str:
    values = _form_list(form, key)
    if index >= len(values):
        return ""
    return values[index].strip()


def _set_if_present(mapping: dict[str, object], key: str, value: str | None) -> None:
    if value is not None and str(value).strip():
        mapping[key] = str(value).strip()


def _set_optional_int(mapping: dict[str, object], key: str, value: str | None) -> None:
    parsed = _optional_int_text(value)
    if parsed is not None:
        mapping[key] = parsed


def _set_optional_float(mapping: dict[str, object], key: str, value: str | None) -> None:
    parsed = _optional_float_text(value)
    if parsed is not None:
        mapping[key] = parsed


def _optional_int_text(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    return int(text)


def _int_text(value: object, default: int) -> int:
    parsed = _optional_int_text(value)
    return default if parsed is None else parsed


def _optional_float_text(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def _text_or_empty(value: object) -> str:
    return "" if value is None else str(value)


def _artifact_url_filter(store: SqliteStore):
    def artifact_url(path: str | None) -> str:
        return _artifact_url(store, path)

    return artifact_url


def _artifact_url(store: SqliteStore, path: str | None) -> str:
    if not path:
        return ""
    try:
        relative = Path(path).resolve().relative_to(store.artifacts_dir.resolve())
    except ValueError:
        return ""
    return "/artifacts/" + quote(str(relative).replace(os.sep, "/"))
