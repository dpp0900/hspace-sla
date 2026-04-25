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


if __name__ == "__main__":
    unittest.main()
