from __future__ import annotations

from dataclasses import dataclass

from sla_launcher.process import run_command


@dataclass(frozen=True)
class InstalledApp:
    package: str
    activity: str
    label: str
    app_wait_activity: str = "*"
    app_wait_package: str = "*"

    def to_dict(self) -> dict[str, str]:
        return {
            "package": self.package,
            "activity": self.activity,
            "app_wait_activity": self.app_wait_activity,
            "app_wait_package": self.app_wait_package,
            "label": self.label,
        }


def list_launchable_apps(adb_path: str, serial: str) -> list[InstalledApp]:
    result = run_command(
        [
            adb_path,
            "-s",
            serial,
            "shell",
            "cmd",
            "package",
            "query-activities",
            "--brief",
            "--components",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
        ],
        timeout=30,
    )
    return parse_launchable_apps(result.stdout)


def parse_launchable_apps(text: str) -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    seen: set[tuple[str, str]] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "/" not in line:
            continue
        package, activity = line.split("/", 1)
        package = package.strip()
        activity = activity.strip()
        if not package or not activity:
            continue

        key = (package, activity)
        if key in seen:
            continue
        seen.add(key)
        apps.append(InstalledApp(package=package, activity=activity, label=_label_for(package, activity)))

    return sorted(apps, key=lambda app: (app.label.lower(), app.package, app.activity))


def _label_for(package: str, activity: str) -> str:
    if package == "com.hspace.testapp":
        return "HSPACE Test App"
    package_tail = package.rsplit(".", 1)[-1]
    activity_tail = activity.rsplit(".", 1)[-1].lstrip("$")
    if package_tail and package_tail.lower() not in {"app", "android"}:
        return package_tail.replace("_", " ").title()
    return activity_tail.replace("_", " ").replace("$", " ").title()
