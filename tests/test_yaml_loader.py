from __future__ import annotations

import unittest

from sla_app.core.yaml_loader import SuiteValidationError, suite_from_yaml_text, suite_to_yaml


VALID_YAML = """name: Demo Suite
app:
  platform: android
  apk: test-apk/build/hspace-test-app-debug.apk
thresholds:
  max_duration_ms: 30000
  max_assertion_failures: 0
  max_metric_violations: 0
scenarios:
  - name: smoke
    steps:
      - action: launch_app
      - action: wait
        timeout_ms: 100
      - action: assert_text
        text: Ready
"""


class YamlLoaderTests(unittest.TestCase):
    def test_loads_valid_suite(self) -> None:
        suite = suite_from_yaml_text(VALID_YAML)

        self.assertEqual(suite.name, "Demo Suite")
        self.assertEqual(suite.app.platform, "android")
        self.assertEqual(suite.scenarios[0].steps[2].action, "assert_text")

    def test_rejects_missing_required_target(self) -> None:
        with self.assertRaisesRegex(SuiteValidationError, "apk or app_package/app_activity"):
            suite_from_yaml_text(
                """name: Broken
app:
  platform: android
scenarios:
  - name: smoke
    steps:
      - action: launch_app
"""
            )

    def test_rejects_unknown_action(self) -> None:
        with self.assertRaisesRegex(SuiteValidationError, "unsupported action"):
            suite_from_yaml_text(
                """name: Broken
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: swipe_forever
"""
            )

    def test_exports_parseable_yaml(self) -> None:
        suite = suite_from_yaml_text(VALID_YAML)
        exported = suite_to_yaml(suite)
        round_tripped = suite_from_yaml_text(exported)

        self.assertEqual(round_tripped.name, suite.name)
        self.assertEqual(round_tripped.scenarios[0].steps[1].timeout_ms, 100)

    def test_loads_extended_appium_sla_actions(self) -> None:
        suite = suite_from_yaml_text(
            """name: Extended Suite
app:
  platform: android
  apk: app.apk
scenarios:
  - name: gesture checks
    steps:
      - action: launch_app
      - action: terminate_app
        package: com.example
      - action: activate_app
        package: com.example
      - action: background_app
        timeout_ms: 1500
      - action: swipe
        direction: up
        percent: 0.75
      - action: scroll
        direction: down
        percent: 1.0
      - action: scroll_to_text
        text: Terms
      - action: back
      - action: assert_visible
        selector: id=com.example:id/login
      - action: assert_not_exists
        selector: id=com.example:id/error
      - action: assert_enabled
        selector: id=com.example:id/login
      - action: assert_attribute
        selector: id=com.example:id/login
        attribute: enabled
        value: "true"
      - action: assert_not_text
        text: Crash
      - action: assert_current_package
        package: com.example
      - action: assert_current_activity
        activity: "*.MainActivity"
"""
        )
        steps = suite.scenarios[0].steps

        self.assertEqual(steps[1].action, "terminate_app")
        self.assertEqual(steps[1].package, "com.example")
        self.assertEqual(steps[4].action, "swipe")
        self.assertEqual(steps[4].direction, "up")
        self.assertEqual(steps[4].percent, 0.75)
        self.assertEqual(steps[11].attribute, "enabled")
        self.assertEqual(steps[14].activity, "*.MainActivity")

        exported = suite_to_yaml(suite)
        self.assertIn("scroll_to_text", exported)
        self.assertIn("assert_not_exists", exported)
        self.assertIn("package: com.example", exported)
        self.assertIn("attribute: enabled", exported)

    def test_rejects_invalid_gesture_direction(self) -> None:
        with self.assertRaisesRegex(SuiteValidationError, "direction"):
            suite_from_yaml_text(
                """name: Broken
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: swipe
        direction: diagonal
"""
            )

    def test_rejects_swipe_percent_over_one(self) -> None:
        with self.assertRaisesRegex(SuiteValidationError, "swipe percent"):
            suite_from_yaml_text(
                """name: Broken
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: swipe
        percent: 2
"""
            )

    def test_rejects_state_assertions_without_expected_value(self) -> None:
        with self.assertRaisesRegex(SuiteValidationError, "assert_current_package requires package"):
            suite_from_yaml_text(
                """name: Broken
app:
  platform: android
  apk: app.apk
scenarios:
  - name: smoke
    steps:
      - action: assert_current_package
"""
            )


if __name__ == "__main__":
    unittest.main()
