from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sla_app.adapters.android_appium import AndroidAppiumAdapter
from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.yaml_loader import SuiteValidationError, suite_from_yaml_text
from sla_app.storage import SqliteStore
from sla_launcher.android import avd_home, detect_host_architecture, load_avd_definitions
from sla_launcher.appium_server import is_appium_server_ready
from sla_launcher.paths import default_sdk_root, platform_executable_name, sdk_tool_path


PACKAGE_DIR = Path(__file__).parent
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


def create_app(base_dir: str | Path | None = None) -> FastAPI:
    app_base_dir = Path(base_dir or os.getenv("SLA_APP_HOME", ".")).resolve()
    store = SqliteStore(app_base_dir)
    _import_existing_suites(store)

    app = FastAPI(title="SLA Test Runner")
    app.state.store = store

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    templates.env.filters["artifact_url"] = _artifact_url_filter(store)

    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    app.mount("/artifacts", StaticFiles(directory=str(store.artifacts_dir)), name="artifacts")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        counts = store.run_counts()
        runs = store.list_runs(limit=10)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "active": "dashboard",
                "counts": counts,
                "runs": runs,
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

    @app.get("/suites/new", response_class=HTMLResponse)
    async def new_suite(request: Request):
        return templates.TemplateResponse(
            request,
            "suite_form.html",
            {
                "active": "suites",
                "title": "New Suite",
                "action": "/suites",
                "yaml_text": DEFAULT_SUITE_YAML,
                "error": None,
            },
        )

    @app.post("/suites")
    async def create_suite(request: Request, yaml_text: str = Form(...)):
        try:
            suite = suite_from_yaml_text(yaml_text)
        except SuiteValidationError as exc:
            return templates.TemplateResponse(
                request,
                "suite_form.html",
                {
                    "active": "suites",
                    "title": "New Suite",
                    "action": "/suites",
                    "yaml_text": yaml_text,
                    "error": str(exc),
                },
                status_code=400,
            )
        store.save_suite(suite, yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/suites/{suite_id}/edit", response_class=HTMLResponse)
    async def edit_suite(request: Request, suite_id: str):
        yaml_text = _suite_yaml_or_404(store, suite_id)
        return templates.TemplateResponse(
            request,
            "suite_form.html",
            {
                "active": "suites",
                "title": "Edit Suite",
                "action": f"/suites/{suite_id}",
                "yaml_text": yaml_text,
                "error": None,
            },
        )

    @app.post("/suites/{suite_id}")
    async def update_suite(request: Request, suite_id: str, yaml_text: str = Form(...)):
        try:
            suite = suite_from_yaml_text(yaml_text)
        except SuiteValidationError as exc:
            return templates.TemplateResponse(
                request,
                "suite_form.html",
                {
                    "active": "suites",
                    "title": "Edit Suite",
                    "action": f"/suites/{suite_id}",
                    "yaml_text": yaml_text,
                    "error": str(exc),
                },
                status_code=400,
            )
        store.save_suite(replace(suite, suite_id=suite_id), yaml_text)
        return RedirectResponse("/suites", status_code=303)

    @app.get("/suites/{suite_id}/export", response_class=PlainTextResponse)
    async def export_suite(suite_id: str):
        return PlainTextResponse(_suite_yaml_or_404(store, suite_id), media_type="text/yaml")

    @app.post("/suites/{suite_id}/runs")
    async def run_suite(suite_id: str):
        try:
            suite = store.load_suite(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run_id = uuid.uuid4().hex
        adapter = AndroidAppiumAdapter.from_suite(suite)
        run = execute_suite(
            suite,
            adapter,
            suite_id=suite_id,
            options=ExecutionOptions(
                run_id=run_id,
                artifact_dir=store.artifact_dir_for_run(run_id),
            ),
        )
        store.save_run(run)
        return RedirectResponse(f"/runs/{run.run_id}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str):
        detail = store.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="run not found")
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "active": "runs",
                "run": detail,
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
            },
        )

    return app


def _suite_yaml_or_404(store: SqliteStore, suite_id: str) -> str:
    try:
        return store.get_suite_yaml(suite_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _import_existing_suites(store: SqliteStore) -> None:
    for path in sorted(store.suites_dir.glob("*.yaml")):
        try:
            suite = suite_from_yaml_text(path.read_text(encoding="utf-8"), source_path=path)
            store.register_suite_file(path.stem, suite, path)
        except SuiteValidationError:
            continue


def _artifact_url_filter(store: SqliteStore):
    artifacts_root = store.artifacts_dir.resolve()

    def artifact_url(path: str | None) -> str:
        if not path:
            return ""
        try:
            relative = Path(path).resolve().relative_to(artifacts_root)
        except ValueError:
            return ""
        return "/artifacts/" + quote(str(relative).replace(os.sep, "/"))

    return artifact_url
