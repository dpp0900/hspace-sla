from __future__ import annotations

import unittest

from sla_app.adapters.android_appium.inspector import extract_ui_elements


PAGE_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" displayed="true" enabled="true">
    <node
      class="android.widget.EditText"
      displayed="true"
      enabled="true"
      focusable="true"
      resource-id="com.example:id/email"
      text=""
      bounds="[16,40][320,96]" />
    <node
      class="android.widget.Button"
      displayed="true"
      enabled="true"
      clickable="true"
      resource-id="com.example:id/login"
      text="Login"
      bounds="[16,112][320,168]" />
    <node
      class="android.widget.ImageButton"
      displayed="true"
      enabled="true"
      clickable="true"
      content-desc="Open menu"
      bounds="[0,0][48,48]" />
    <node
      class="android.widget.TextView"
      displayed="false"
      enabled="true"
      text="Hidden" />
  </node>
</hierarchy>
"""


class InspectorTests(unittest.TestCase):
    def test_extracts_stable_element_candidates(self) -> None:
        elements = extract_ui_elements(PAGE_SOURCE)

        selectors = [element.get("selector") for element in elements]
        labels = [element["label"] for element in elements]
        class_names = [element.get("class_name") for element in elements]

        self.assertIn("id=com.example:id/email", selectors)
        self.assertIn("id=com.example:id/login", selectors)
        self.assertIn("accessibility_id=Open menu", selectors)
        self.assertIn("Login", labels)
        self.assertNotIn("Hidden", labels)
        self.assertNotIn("android.widget.FrameLayout", class_names)

    def test_advanced_mode_includes_low_level_nodes(self) -> None:
        elements = extract_ui_elements(PAGE_SOURCE, mode="advanced")

        frame_layout = next(
            element for element in elements if element.get("class_name") == "android.widget.FrameLayout"
        )
        labels = [element["label"] for element in elements]

        self.assertEqual(frame_layout["selector"], 'xpath=//*[@class="android.widget.FrameLayout"]')
        self.assertEqual(frame_layout["confidence"], "fallback")
        self.assertNotIn("Hidden", labels)

    def test_deduplicates_elements(self) -> None:
        duplicated = PAGE_SOURCE.replace("</hierarchy>", PAGE_SOURCE.split("<hierarchy>", 1)[1])

        elements = extract_ui_elements(duplicated)
        login_matches = [
            element for element in elements if element.get("selector") == "id=com.example:id/login"
        ]

        self.assertEqual(len(login_matches), 1)


if __name__ == "__main__":
    unittest.main()
