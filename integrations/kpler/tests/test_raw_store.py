"""Unit tests for Kpler raw response store."""
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from integrations.kpler.expected_arrivals import fetch_expected_arrivals
from integrations.kpler.graphql import fetch_particulars
from integrations.kpler.raw_store import save_raw_response


class RawStoreTests(SimpleTestCase):
    def test_save_raw_response_envelope_and_file_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(KPLER_RAW_DIR=Path(tmp_dir)):
                payload = [{"key": "value"}]
                saved_path = save_raw_response("marinetraffic", "test_label", payload)

                self.assertTrue(saved_path.exists())
                self.assertIn("marinetraffic", str(saved_path))
                self.assertTrue(saved_path.name.endswith("_test_label.json"))

                with open(saved_path, "r", encoding="utf-8") as f:
                    content = json.load(f)

                self.assertEqual(content["service"], "marinetraffic")
                self.assertEqual(content["label"], "test_label")
                self.assertIn("saved_at", content)
                self.assertEqual(content["payload"], payload)

    @override_settings(MARINETRAFFIC_API_KEY="test-mt-key")
    @patch("integrations.kpler.expected_arrivals.requests.get")
    @patch("integrations.kpler.expected_arrivals.save_raw_response")
    def test_expected_arrivals_save_failure_does_not_lose_data(self, mock_save, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"vessel": "test"}]
        mock_get.return_value = mock_resp
        mock_save.side_effect = OSError("Disk write failed")

        # Must not raise OSError; must return payload cleanly
        result = fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(result, [{"vessel": "test"}])
        mock_save.assert_called_once()

    @override_settings(KPLER_API_KEY="test-kp-key")
    @patch("integrations.kpler.graphql.requests.post")
    @patch("integrations.kpler.graphql.save_raw_response")
    def test_graphql_save_failure_does_not_lose_data(self, mock_save, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "vessels": {
                    "nodes": [{"identifier": {"imo": "9697428"}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
        mock_post.return_value = mock_resp
        mock_save.side_effect = PermissionError("Permission denied")

        result = fetch_particulars(["9697428"])
        self.assertEqual(len(result), 1)
        mock_save.assert_called_once()
