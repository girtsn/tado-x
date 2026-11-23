"""Contract test: Vaillant quality scan supports response-optional calls.

HA scripts without response_variable must not fail before the diagnostic
has had a chance to execute. Scripts that capture a response must continue
to receive its unchanged report.
"""

from pathlib import Path
import re
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "tado"
    / "services.py"
)


class VaillantScanServiceResponseTests(unittest.TestCase):
    def test_scan_registration_accepts_script_without_response_variable(self):
        source = SOURCE.read_text()
        match = re.search(
            r'hass\.services\.async_register\(\s*DOMAIN,\s*'
            r'"x_scan_vaillant_hourly_quality",'
            r'(?P<arguments>.*?)\n\s*\)\n',
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, "Vaillant scan action not registered")
        self.assertIn(
            "supports_response=SupportsResponse.OPTIONAL",
            match.group("arguments"),
            "Response-only services fail when a HA script omits "
            "response_variable.",
        )
        self.assertNotIn(
            "SupportsResponse.ONLY",
            match.group("arguments"),
        )

    def test_scan_still_returns_quality_report(self):
        source = SOURCE.read_text()
        method = re.search(
            r'async def x_scan_vaillant_hourly_quality\(call: ServiceCall\)'
            r' -> dict:(?P<body>.*?)\n\s*hass\.services\.async_register',
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(method)
        self.assertIn("return await detect_vaillant_hourly_start(",method.group("body"))


if __name__ == "__main__":
    unittest.main()
