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
from sla_app.core.models import ActionStep, AppTarget, MetricLimit, Scenario, SlaThresholds, TestSuite
from sla_app.core.yaml_loader import SuiteValidationError, suite_from_yaml_text, suite_to_yaml
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

    @app.get("/suites/builder", response_class=HTMLResponse)
    async def suite_builder(request: Request):
        return templates.TemplateResponse(
            request,
            "suite_builder.html",
            {
                "active": "suites",
                "builder": _default_builder_state(),
                "error": None,
            },
        )

    @app.post("/suites/builder")
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
                    "builder": builder,
                    "error": str(exc),
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


def _default_builder_state() -> dict[str, object]:
    return {
        "suite_name": "Android Smoke",
        "target_mode": "apk",
        "apk": "test-apk/build/hspace-test-app-debug.apk",
        "app_package": "",
        "app_activity": "",
        "app_wait_activity": "",
        "no_reset": False,
        "max_duration_ms": "30000",
        "max_assertion_failures": "0",
        "max_metric_violations": "0",
        "required_assertions": "",
        "memory_mb_max": "",
        "scenario_name": "launch and capture",
        "steps": [
            {"action": "launch_app"},
            {"action": "wait", "timeout_ms": "1000"},
            {"action": "screenshot", "name": "launch"},
        ],
    }


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
        "no_reset": form.get("no_reset") == "true",
        "max_duration_ms": _form_value(form, "max_duration_ms"),
        "max_assertion_failures": _form_value(form, "max_assertion_failures", "0"),
        "max_metric_violations": _form_value(form, "max_metric_violations", "0"),
        "required_assertions": _form_value(form, "required_assertions"),
        "memory_mb_max": _form_value(form, "memory_mb_max"),
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
        if builder.get("no_reset"):
            app_data["no_reset"] = True
    else:
        app_data["apk"] = str(builder.get("apk") or "")

    metrics = {}
    memory_mb_max = _optional_float_text(builder.get("memory_mb_max"))
    if memory_mb_max is not None:
        metrics["memory_mb"] = MetricLimit(max=memory_mb_max)

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


def _step_mapping_from_builder(step: dict[str, str]) -> dict[str, object]:
    action = str(step.get("action") or "")
    mapping: dict[str, object] = {"action": action}
    if action in {"tap", "assert_exists"}:
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "text", step.get("text"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "input":
        _set_if_present(mapping, "selector", step.get("selector"))
        _set_if_present(mapping, "value", step.get("value"))
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "wait":
        _set_optional_int(mapping, "timeout_ms", step.get("timeout_ms"))
    elif action == "assert_text":
        _set_if_present(mapping, "text", step.get("text"))
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
