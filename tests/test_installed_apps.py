from __future__ import annotations

import unittest

from sla_app.adapters.android_appium.installed_apps import parse_launchable_apps


class InstalledAppsTests(unittest.TestCase):
    def test_parses_launchable_activity_output(self) -> None:
        apps = parse_launchable_apps(
            """
            com.android.settings/.Settings
            com.hspace.testapp/.MainActivity
            com.hspace.testapp/.MainActivity
            invalid line
            """
        )

        packages = [app.package for app in apps]
        self.assertIn("com.android.settings", packages)
        self.assertIn("com.hspace.testapp", packages)
        self.assertEqual(packages.count("com.hspace.testapp"), 1)

        hspace = next(app for app in apps if app.package == "com.hspace.testapp")
        self.assertEqual(hspace.activity, ".MainActivity")
        self.assertEqual(hspace.label, "HSPACE Test App")


if __name__ == "__main__":
    unittest.main()
