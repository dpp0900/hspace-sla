from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sla_app.adapters.android_appium import AndroidAppiumAdapter
from sla_app.adapters.android_appium.installed_apps import list_launchable_apps
from sla_app.core.engine import ExecutionOptions, execute_suite
from sla_app.core.models import ActionStep, AppTarget, MetricLimit, Scenario, SlaThresholds, TestSuite
from sla_app.core.yaml_loader import SuiteValidationError, suite_from_yaml_text, suite_to_yaml
from sla_app.storage import SqliteStore
from sla_launcher.android import avd_home, detect_host_architecture, ensure_emulator, load_avd_definitions
from sla_launcher.appium_server import is_appium_server_ready
from sla_launcher.config import LaunchConfig
from sla_launcher.diagnostics import collect_environment_diagnostics
from sla_launcher.paths import default_sdk_root, platform_executable_name, sdk_tool_path
from sla_launcher.process import resolve_executable, resolve_sdk_root


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

    app = FastAPI(title="SLA 테스트 러너")
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
                    "title": "새 스위트",
                    "action": "/suites",
                    "yaml_text": yaml_text,
                    "error": str(exc),
                },
                status_code=400,
            )
        store.save_suite(suite, yaml_text)
        return RedirectResponse("/suites", status_code=303)

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

    @app.post("/suites/{suite_id}/edit/helper")
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

    @app.post("/suites/{suite_id}")
    async def update_suite(request: Request, suite_id: str, yaml_text: str = Form(...)):
        return await update_suite_yaml(request, suite_id, yaml_text)

    @app.post("/suites/{suite_id}/edit/yaml")
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

    @app.post("/suites/{suite_id}/delete")
    async def delete_suite(suite_id: str):
        if not store.delete_suite(suite_id):
            raise HTTPException(status_code=404, detail="스위트를 찾지 못했습니다")
        return RedirectResponse("/suites", status_code=303)

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
            raise HTTPException(status_code=404, detail="실행 결과를 찾지 못했습니다")
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "active": "runs",
                "run": detail,
                "insights": _run_insights(detail),
                "comparison": _run_comparison(store, detail),
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

    @app.get("/settings/diagnostics")
    async def settings_diagnostics():
        return JSONResponse(collect_environment_diagnostics(_android_discovery_config()))

    return app


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


def _run_insights(run: dict) -> list[dict[str, str]]:
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
    suite_id = run.get("suite_id")
    run_id = run.get("run_id")
    started_at = str(run.get("started_at") or "")
    previous = None
    for candidate in store.list_runs(limit=100):
        if candidate.suite_id != suite_id or candidate.run_id == run_id:
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
    if "text not found" in message or action == "assert_text":
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
    if "text not found" in normalized:
        return "텍스트를 찾지 못했습니다. 앱 화면 문구가 바뀌었거나 실행 타이밍이 빠를 수 있습니다."
    if action == "metric_check":
        return "수집된 지표가 설정한 최소/최대 기준을 벗어났습니다."
    if message:
        return message
    return "상세 메시지가 없습니다."


def _step_action_label(action: str) -> str:
    return {
        "launch_app": "앱 실행",
        "tap": "탭",
        "input": "입력",
        "wait": "대기",
        "assert_text": "텍스트 검증",
        "assert_exists": "요소 존재 검증",
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
    memory_limit = suite.thresholds.metrics.get("memory_mb")
    if metric_names - {"memory_mb"}:
        reasons.append("커스텀 스위트 지표 기준은 YAML 편집이 필요합니다.")
    if memory_limit and memory_limit.min is not None:
        reasons.append("메모리 최소 기준은 YAML 편집이 필요합니다.")

    supported_step_keys = {"action", "selector", "text", "value", "timeout_ms", "name", "metric", "min", "max"}
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


def _text_or_empty(value: object) -> str:
    return "" if value is None else str(value)


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
