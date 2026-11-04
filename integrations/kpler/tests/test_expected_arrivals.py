"""Unit tests for MarineTraffic Expected Arrivals client."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
import requests

from integrations.kpler.exceptions import (
    AuthenticationError,
    CallLimitError,
    ParameterError,
    ProviderRequestError,
    ServiceNotInContractError,
)
from integrations.kpler.expected_arrivals import fetch_expected_arrivals


@override_settings(
    MARINETRAFFIC_API_KEY="test-mt-key",
    MARINETRAFFIC_BASE_URL="https://services.marinetraffic.com/api",
    EXPECTED_ARRIVALS_TIMESPAN_DAYS=14,
    EXPECTED_ARRIVALS_DAYS_LAST_SIGNAL=1,
    EXPECTED_ARRIVALS_GT_MIN=3000,
    EXPECTED_ARRIVALS_GT_MAX=500000,
)
class ExpectedArrivalsClientTests(SimpleTestCase):
    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_url_and_params_for_arrivals_mode(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"MMSI": "123456789", "SHIPNAME": "TEST SHIP"}]
        mock_get.return_value = mock_resp

        result = fetch_expected_arrivals(290, mode="arrivals")

        self.assertEqual(len(result), 1)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        called_url = args[0]
        self.assertEqual(called_url, "https://services.marinetraffic.com/api/expectedarrivals/test-mt-key")

        params = kwargs["params"]
        self.assertEqual(params["v"], 4)
        self.assertEqual(params["portid"], 290)
        self.assertEqual(params["protocol"], "jsono")
        self.assertEqual(params["msgtype"], "extended")
        self.assertEqual(params["timespan"], 14)
        self.assertEqual(params["gt_min"], 3000)
        self.assertEqual(params["gt_max"], 500000)
        self.assertNotIn("days_last_signal", params)

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_url_and_params_for_inport_mode(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        result = fetch_expected_arrivals(790, mode="inport", days_last_signal=3, gt_min=5000, gt_max=100000)

        self.assertEqual(result, [])
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        params = kwargs["params"]
        self.assertEqual(params["days_last_signal"], 3)
        self.assertEqual(params["gt_min"], 5000)
        self.assertEqual(params["gt_max"], 100000)
        self.assertNotIn("timespan", params)

    def test_window_and_size_pair_validation(self):
        # Both windows given
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="arrivals", timespan_days=10, days_last_signal=2)

        # Invalid mode
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="unknown_mode")

        # Inport mode with timespan
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="inport", timespan_days=10)

        # Arrivals mode with days_last_signal
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="arrivals", days_last_signal=2)

        # Only gt_min provided
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="arrivals", gt_min=1000)

        # Only gt_max provided
        with self.assertRaises(ValueError):
            fetch_expected_arrivals(290, mode="arrivals", gt_max=5000)

    @override_settings(MARINETRAFFIC_API_KEY="")
    def test_missing_api_key_raises_value_error_before_network(self):
        with patch("integrations.kpler.expected_arrivals.requests.get") as mock_get:
            with self.assertRaises(ValueError):
                fetch_expected_arrivals(290, mode="arrivals")
            mock_get.assert_not_called()

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_error_mapping_code_5_and_http_429(self, mock_get):
        # Provider code 5
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": [{"code": "5", "detail": "ABOVE SERVICE CALL LIMIT"}]}
        mock_get.return_value = mock_resp

        with self.assertRaises(CallLimitError) as ctx:
            fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(ctx.exception.provider_code, "5")

        # HTTP 429
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.json.return_value = {"detail": "Rate limit exceeded"}
        mock_get.return_value = mock_resp_429

        with self.assertRaises(CallLimitError):
            fetch_expected_arrivals(290, mode="arrivals")

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_error_mapping_code_2a12_and_1o(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errors": [{"code": "2a12", "detail": "Please provide either timespan or days_last_signal"}]
        }
        mock_get.return_value = mock_resp

        with self.assertRaises(ParameterError) as ctx:
            fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(ctx.exception.provider_code, "2a12")

        mock_resp.json.return_value = {"errors": [{"code": "1o", "detail": "Bad parameter"}]}
        with self.assertRaises(ParameterError) as ctx:
            fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(ctx.exception.provider_code, "1o")

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_error_mapping_code_12_service_not_in_contract(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errors": [{"code": "12", "detail": "SERVICE KEY DOES NOT MATCH SERVICE TYPE"}]
        }
        mock_get.return_value = mock_resp

        with self.assertRaises(ServiceNotInContractError) as ctx:
            fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(ctx.exception.provider_code, "12")

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_error_mapping_unknown_code_and_http_status_codes(self, mock_get):
        # Unknown error code
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": [{"code": "999", "detail": "Custom error"}]}
        mock_get.return_value = mock_resp

        with self.assertRaises(ProviderRequestError) as ctx:
            fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(ctx.exception.provider_code, "999")

        # HTTP 401
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_get.return_value = mock_resp_401
        with self.assertRaises(AuthenticationError):
            fetch_expected_arrivals(290, mode="arrivals")

        # HTTP 500
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        mock_resp_500.json.side_effect = ValueError("Not JSON")
        mock_get.return_value = mock_resp_500
        with self.assertRaises(ProviderRequestError):
            fetch_expected_arrivals(290, mode="arrivals")

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_synthetic_two_records_returned_unchanged(self, mock_get):
        records = [
            {"MMSI": "111", "SHIPNAME": "ALPHA", "DWT": 50000},
            {"MMSI": "222", "SHIPNAME": "BETA", "DWT": 80000},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = records
        mock_get.return_value = mock_resp

        result = fetch_expected_arrivals(290, mode="arrivals")
        self.assertEqual(result, records)

    @patch("integrations.kpler.expected_arrivals.requests.get")
    def test_failed_call_is_made_exactly_once_no_retries(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        with self.assertRaises(ProviderRequestError):
            fetch_expected_arrivals(290, mode="arrivals")

        self.assertEqual(mock_get.call_count, 1)
