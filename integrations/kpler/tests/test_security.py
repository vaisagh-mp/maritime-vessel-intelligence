"""Security and leak-prevention tests for Kpler & MarineTraffic integration."""
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
import requests

from integrations.kpler.expected_arrivals import fetch_expected_arrivals
from integrations.kpler.graphql import fetch_particulars
from integrations.kpler.raw_store import save_raw_response


class SecurityKeyLeakTests(SimpleTestCase):
    @override_settings(
        MARINETRAFFIC_API_KEY="SENTINEL-KEY-123-MT",
        MARINETRAFFIC_BASE_URL="https://services.marinetraffic.com/api",
    )
    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_marinetraffic_key_never_in_logs_or_exception_strings(self, mock_get):
        sentinel = "SENTINEL-KEY-123-MT"
        mock_get.side_effect = requests.exceptions.ConnectionError(
            f"Failed to connect to https://services.marinetraffic.com/api/expectedarrivals/{sentinel}"
        )

        with self.assertLogs("vessel_intel", level="INFO") as captured:
            try:
                fetch_expected_arrivals(290, mode="arrivals")
            except Exception as exc:
                exc_str = str(exc)
                self.assertNotIn(sentinel, exc_str)

        all_logs = " ".join(captured.output)
        self.assertNotIn(sentinel, all_logs)
        self.assertIn("{api_key}", all_logs)

    @override_settings(
        KPLER_API_KEY="SENTINEL-KEY-456-KP",
        KPLER_GRAPHQL_URL="https://api.kpler.com/v2/maritime/vessels/graphql",
    )
    @patch("integrations.kpler.graphql.requests.post")
    def test_kpler_key_never_in_logs_or_exception_strings(self, mock_post):
        sentinel = "SENTINEL-KEY-456-KP"
        mock_post.side_effect = requests.exceptions.RequestException(
            f"Failed request with Basic {sentinel}"
        )

        with self.assertLogs("vessel_intel", level="INFO") as captured:
            try:
                fetch_particulars(["9697428"])
            except Exception as exc:
                exc_str = str(exc)
                self.assertNotIn(sentinel, exc_str)

        all_logs = " ".join(captured.output)
        self.assertNotIn(sentinel, all_logs)

    def test_raw_store_never_contains_key(self):
        sentinel = "SENTINEL-KEY-RAW-789"
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(KPLER_RAW_DIR=Path(tmp_dir)):
                payload = {"data": "sample_vessel_telemetry"}
                file_path = save_raw_response("test_service", "test_label", payload)

                raw_content = file_path.read_text(encoding="utf-8")
                self.assertNotIn(sentinel, raw_content)
