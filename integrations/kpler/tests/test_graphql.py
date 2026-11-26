"""Unit tests for Kpler GraphQL client."""
import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
import requests

from integrations.kpler.exceptions import (
    AuthenticationError,
    NotEntitledError,
    ParameterError,
    ProviderRequestError,
)
from integrations.kpler.graphql import fetch_ownership, fetch_particulars


@override_settings(
    KPLER_API_KEY="test-kpler-key",
    KPLER_GRAPHQL_URL="https://api.kpler.com/v2/maritime/vessels/graphql",
    KPLER_HTTP_TIMEOUT_SECONDS=30,
    KPLER_GRAPHQL_PAGE_SIZE=100,
)
class GraphQLClientTests(SimpleTestCase):
    @patch("integrations.kpler.graphql.requests.post")
    def test_auth_header_and_inline_filter(self, mock_post):
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

        result = fetch_particulars(["9697428"])

        self.assertEqual(len(result), 1)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.kpler.com/v2/maritime/vessels/graphql")

        headers = kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Basic test-kpler-key")
        self.assertEqual(headers["Content-Type"], "application/json")

        body = kwargs["json"]
        query = body["query"]
        self.assertIn(
            'where: { filters: [{ field: "identifier.imo", op: IN, values: ["9697428"] }], operator: AND }, after: null',
            query,
        )

    def test_imo_validation_and_deduplication(self):
        # Invalid IMOs raise ValueError
        for bad_imo in ["12345", "12345678", "ABC4567", "", None]:
            with self.assertRaises(ValueError):
                fetch_particulars([bad_imo])

        # Deduplication preserving order
        with patch("integrations.kpler.graphql.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {"vessels": {"nodes": []}}}
            mock_post.return_value = mock_resp

            fetch_particulars(["9697428", " 9697428 ", "9123456", "9697428"])
            query = mock_post.call_args[1]["json"]["query"]
            self.assertIn('values: ["9697428", "9123456"]', query)

    @override_settings(KPLER_API_KEY="")
    def test_missing_api_key_raises_value_error(self):
        with patch("integrations.kpler.graphql.requests.post") as mock_post:
            with self.assertRaises(ValueError):
                fetch_particulars(["9697428"])
            mock_post.assert_not_called()

    @override_settings(KPLER_GRAPHQL_PAGE_SIZE=2)
    @patch("integrations.kpler.graphql.requests.post")
    def test_chunking_by_page_size(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"vessels": {"nodes": []}}}
        mock_post.return_value = mock_resp

        fetch_particulars(["1000001", "1000002", "1000003", "1000004", "1000005"])

        # 5 IMOs chunked by 2 = 3 requests
        self.assertEqual(mock_post.call_count, 3)

    @patch("integrations.kpler.graphql.requests.post")
    def test_cursor_following_with_5_page_cap(self, mock_post):
        # Simulate infinite hasNextPage
        def mock_side_effect(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": {
                    "vessels": {
                        "nodes": [{"identifier": {"imo": "9697428"}}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor_next"},
                    }
                }
            }
            return resp

        mock_post.side_effect = mock_side_effect

        result = fetch_particulars(["9697428"])

        # Must stop at 5 pages
        self.assertEqual(mock_post.call_count, 5)
        self.assertEqual(len(result), 5)

    @patch("integrations.kpler.graphql.requests.post")
    def test_not_entitled_error_extracts_field(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": None,
            "errors": [
                {
                    "message": "Not sufficient permissions to access field [management]",
                    "path": ["vessels", "nodes", 0, "management"],
                    "extensions": {"code": "FORBIDDEN", "originalError": {"statusCode": 403}},
                }
            ],
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(NotEntitledError) as ctx:
            fetch_ownership(["9697428"])

        self.assertEqual(ctx.exception.field, "management")

    @patch("integrations.kpler.graphql.requests.post")
    def test_error_mapping_401_400_and_server_error(self, mock_post):
        # 401
        resp_401 = MagicMock()
        resp_401.status_code = 401
        mock_post.return_value = resp_401
        with self.assertRaises(AuthenticationError):
            fetch_particulars(["9697428"])

        # 400 with GRAPHQL_VALIDATION_FAILED
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.json.return_value = {
            "errors": [{"message": "Syntax Error", "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]
        }
        mock_post.return_value = resp_400
        with self.assertRaises(ParameterError):
            fetch_particulars(["9697428"])

        # 500 server error
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.json.side_effect = ValueError("Not JSON")
        mock_post.return_value = resp_500
        with self.assertRaises(ProviderRequestError):
            fetch_particulars(["9697428"])

    @patch("integrations.kpler.graphql.requests.post")
    def test_ownership_query_structure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "vessels": {
                    "nodes": [
                        {
                            "identifier": {"imo": "9697428"},
                            "management": {"technicalManager": {"current": {"name": "Tech Corp"}}},
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
        mock_post.return_value = mock_resp

        res = fetch_ownership(["9697428"])
        self.assertEqual(len(res), 1)
        query = mock_post.call_args[1]["json"]["query"]
        self.assertIn("technicalManager", query)
        self.assertIn("beneficialOwner", query)
        self.assertIn("commercialOperator", query)

    @patch("integrations.kpler.graphql.requests.post")
    def test_fetch_vessels_batch_size_capped_at_20(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"vessels": {"nodes": []}}}
        mock_post.return_value = mock_resp

        from integrations.kpler.graphql import fetch_vessels
        # 25 IMOs should chunk into 2 requests (20 and 5)
        imos = [f"90000{i:02d}" for i in range(25)]
        fetch_vessels(imos)

        self.assertEqual(mock_post.call_count, 2)
        q1 = mock_post.call_args_list[0][1]["json"]["query"]
        q2 = mock_post.call_args_list[1][1]["json"]["query"]
        self.assertIn("vessels(first: 20", q1)
        self.assertIn("vessels(first: 5", q2)
        # Check query fields
        self.assertIn("technicalManager", q1)
        self.assertIn("ismManager", q1)
        self.assertIn("commercialManager", q1)
        self.assertIn("operator", q1)
        self.assertIn("registeredOwner", q1)
        self.assertIn("beneficialOwner", q1)
        self.assertIn("grossTonnage", q1)
        self.assertIn("deadweightTonnage", q1)
        # Verify it does NOT query disponentOwner/commercialOperator/builder/classSociety
        self.assertNotIn("disponentOwner", q1)
        self.assertNotIn("commercialOperator", q1)

    @patch("integrations.kpler.graphql.requests.post")
    def test_fetch_vessels_forbidden_raises_kpler_access_error(self, mock_post):
        from integrations.kpler.exceptions import KplerAccessError
        from integrations.kpler.graphql import fetch_vessels

        # GraphQL FORBIDDEN error
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errors": [
                {
                    "message": "Not sufficient permissions to access field [management]",
                    "extensions": {"code": "FORBIDDEN"},
                }
            ]
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(KplerAccessError) as ctx:
            fetch_vessels(["9697428"])
        self.assertIn("Vessels particulars and ownership are not enabled for this key", str(ctx.exception))

        # HTTP 403
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.json.return_value = {"message": "Forbidden"}
        mock_post.return_value = resp_403

        with self.assertRaises(KplerAccessError):
            fetch_vessels(["9697428"])

    @patch("integrations.kpler.graphql.requests.post")
    def test_fetch_vessels_rate_limit_and_auth_error(self, mock_post):
        from integrations.kpler.exceptions import AuthenticationError, CallLimitError
        from integrations.kpler.graphql import fetch_vessels

        # 401
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_post.return_value = mock_resp_401

        with self.assertRaises(AuthenticationError):
            fetch_vessels(["9697428"])

        # 429
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_post.return_value = mock_resp_429

        with self.assertRaises(CallLimitError):
            fetch_vessels(["9697428"])

