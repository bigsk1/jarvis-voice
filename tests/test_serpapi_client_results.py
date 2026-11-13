#!/usr/bin/env python3
"""Regression tests for SerpApi result normalization."""

import gzip
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from urllib3.response import HTTPResponse

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from serpapi_client import extract_generic_results, request_serpapi


class SerpApiClientResultsTests(unittest.TestCase):
    def _stream_response(self, body, *, status=200, compressed=False):
        headers = {"Content-Encoding": "gzip"} if compressed else {}
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers)
        response.raw = HTTPResponse(
            body=io.BytesIO(gzip.compress(body) if compressed else body),
            headers=headers, preload_content=False,
        )
        response.close = Mock(wraps=response.close)
        response.json = Mock(side_effect=AssertionError("Unbounded JSON parser used"))
        return response

    def _capped_request(self, response, maximum):
        with patch("serpapi_client.get_api_key", return_value="test-key"), patch(
            "serpapi_client.http_request", return_value=response,
        ):
            return request_serpapi({"engine": "extract"}, max_response_bytes=maximum)

    def test_uncapped_requests_preserve_existing_parser_and_transport_arguments(self):
        payload = {"markdown": "Existing response"}
        response = SimpleNamespace(status_code=200, json=Mock(return_value=payload))
        with patch("serpapi_client.get_api_key", return_value="test-key"), patch(
            "serpapi_client.http_request", return_value=response,
        ) as request:
            self.assertEqual(request_serpapi({"engine": "google"}), payload)
        self.assertNotIn("stream", request.call_args.kwargs)
        response.json.assert_called_once_with()

    def test_capped_response_accepts_exact_byte_boundary_and_requests_streaming(self):
        payload = {"markdown": "Café and useful evidence"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._stream_response(body)
        with patch("serpapi_client.get_api_key", return_value="test-key"), patch(
            "serpapi_client.http_request", return_value=response,
        ) as request:
            self.assertEqual(request_serpapi({"engine": "extract"}, max_response_bytes=len(body)), payload)
        self.assertIs(request.call_args.kwargs["stream"], True)
        response.json.assert_not_called()
        response.close.assert_called_once_with()
        response = self._stream_response(body)
        with self.assertRaisesRegex(RuntimeError, "size limit"):
            self._capped_request(response, len(body) - 1)
        response.close.assert_called_once_with()

    def test_oversized_stream_and_error_bodies_are_rejected_before_json_parsing(self):
        body = b'{"error":"PRIVATE_BODY_AND_URL https://private.test/secret"}'
        for status in (200, 400):
            with self.subTest(status=status):
                response = self._stream_response(body, status=status)
                with self.assertRaisesRegex(RuntimeError, "^SerpApi response exceeded the size limit\\.$"):
                    self._capped_request(response, len(body) - 1)
                response.json.assert_not_called()
                response.close.assert_called_once_with()

    def test_size_limit_stops_reading_instead_of_consuming_the_remaining_response(self):
        response = self._stream_response(b"")
        consumed = []

        def chunks(**_kwargs):
            for block in (b'{"a":', b'"oversized"', b'"NEVER_CONSUME_THIS"}'):
                consumed.append(block)
                yield block

        response.iter_content = chunks
        with self.assertRaisesRegex(RuntimeError, "size limit"):
            self._capped_request(response, 10)
        self.assertEqual(len(consumed), 2)
        response.close.assert_called_once_with()

    def test_gzip_limit_counts_decoded_bytes_without_content_length(self):
        payload = {"markdown": "article evidence " * 200}
        body = json.dumps(payload).encode()
        self.assertLess(len(gzip.compress(body)), len(body) // 2)
        for maximum, succeeds in ((len(body), True), (len(body) - 1, False)):
            with self.subTest(maximum=maximum):
                response = self._stream_response(body, compressed=True)
                self.assertNotIn("Content-Length", response.headers)
                if succeeds:
                    self.assertEqual(self._capped_request(response, maximum), payload)
                else:
                    with self.assertRaisesRegex(RuntimeError, "size limit"):
                        self._capped_request(response, maximum)
                response.close.assert_called_once_with()

    def test_capped_parse_failures_are_constant_and_provider_details_remain_sanitized(self):
        cases = [
            (200, b'PRIVATE_MALFORMED_JSON https://private.test/secret', "SerpApi returned invalid JSON."),
            (400, b'PRIVATE_MALFORMED_JSON https://private.test/secret', "SerpApi request failed with HTTP 400."),
            (400, b'{"error":"Quota exceeded: api_key=provider-secret-token-123"}',
             "SerpApi request failed with HTTP 400: Quota exceeded: api_key=[redacted]."),
            (200, b'{"error":"Robots blocked; api_key=provider-secret-token-123"}',
             "SerpApi error: Robots blocked; api_key=[redacted]"),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, expected=expected):
                response = self._stream_response(body, status=status)
                with self.assertRaises(RuntimeError) as raised:
                    self._capped_request(response, 1024)
                self.assertEqual(str(raised.exception), expected)
                response.close.assert_called_once_with()

    def test_capped_stream_failure_closes_response_without_echoing_private_error(self):
        response = self._stream_response(b"")

        def interrupted(**_kwargs):
            yield b'{"markdown":'
            raise RuntimeError("PRIVATE_ERROR https://private.test/path?api_key=secret")

        response.iter_content = interrupted
        with self.assertRaises(RuntimeError) as raised:
            self._capped_request(response, 1024)
        self.assertEqual(str(raised.exception), "SerpApi response download failed.")
        response.close.assert_called_once_with()

    def test_invalid_cap_is_rejected_before_any_provider_call(self):
        for maximum in (0, -1, True, "1024"):
            with self.subTest(maximum=maximum), patch("serpapi_client.http_request") as request:
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    request_serpapi({"engine": "extract"}, max_response_bytes=maximum)
                request.assert_not_called()

    def test_non_object_success_response_returns_safe_error(self):
        for payload in (None, [], ["untrusted provider value"], "unexpected"):
            with self.subTest(payload=payload):
                response = SimpleNamespace(status_code=200, json=lambda: payload)
                with patch("serpapi_client.get_api_key", return_value="test-key"), patch(
                    "serpapi_client.http_request", return_value=response
                ):
                    with self.assertRaisesRegex(RuntimeError, "invalid JSON object"):
                        request_serpapi({"engine": "extract"})

    def test_request_error_redacts_api_key_from_exception_text(self):
        secret = "provider-secret-value-1234567890"
        with patch("serpapi_client.get_api_key", return_value=secret), patch(
            "serpapi_client.http_request",
            side_effect=RuntimeError(
                f"failed https://serpapi.com/search.json?api_key={secret}&output=json"
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                request_serpapi({"engine": "google_travel_explore"})

        message = str(raised.exception)
        self.assertNotIn(secret, message)
        self.assertIn("api_key=[redacted]", message)

    def test_http_error_includes_safe_provider_message(self):
        response = SimpleNamespace(
            status_code=400,
            json=lambda: {"error": "Invalid `page_token` parameter."},
        )
        with patch("serpapi_client.get_api_key", return_value="test-key"), patch(
            "serpapi_client.http_request", return_value=response
        ):
            with self.assertRaises(RuntimeError) as raised:
                request_serpapi({"engine": "google_immersive_product"})

        self.assertEqual(
            str(raised.exception),
            "SerpApi request failed with HTTP 400: Invalid `page_token` parameter.",
        )

    def test_amazon_product_includes_shopping_signals(self):
        payload = {
            "product_results": {
                "title": "Example Product",
                "link": "https://amazon.com/dp/B000TEST",
                "asin": "B000TEST",
                "price": "$149.99",
                "extracted_price": 149.99,
                "rating": 4.8,
                "reviews": 1200,
                "thumbnail": "https://example.com/thumb.jpg",
                "prime": True,
                "delivery": ["FREE delivery Tomorrow"],
                "shipping": "Ships from Amazon",
                "availability": "In Stock",
                "old_price": "$179.99",
                "extracted_old_price": 179.99,
                "save_with_coupon": "Save 10% with coupon",
            }
        }
        results = extract_generic_results(payload, engine="amazon_product", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/thumb.jpg")
        self.assertEqual(results[0]["asin"], "B000TEST")
        self.assertTrue(results[0]["prime"])
        self.assertEqual(results[0]["delivery"], ["FREE delivery Tomorrow"])
        self.assertEqual(results[0]["shipping"], "Ships from Amazon")
        self.assertEqual(results[0]["availability"], "In Stock")
        self.assertEqual(results[0]["extracted_old_price"], 179.99)
        self.assertEqual(results[0]["save_with_coupon"], "Save 10% with coupon")
        self.assertTrue(results[0]["prime_eligible"])

    def test_amazon_search_result_includes_shopping_signals(self):
        payload = {
            "organic_results": [
                {
                    "title": "Example Search Result",
                    "link": "https://amazon.com/dp/B000TEST2",
                    "asin": "B000TEST2",
                    "price": "$99.99",
                    "extracted_price": 99.99,
                    "rating": 4.5,
                    "reviews": 42,
                    "thumbnail": "https://example.com/item.jpg",
                    "prime": True,
                    "delivery": ["FREE delivery Wed, Jul 29"],
                    "shipping": "Free shipping",
                    "stock": "Only 8 left in stock",
                    "bought_last_month": "2K+ bought in past month",
                    "badges": ["Overall Pick"],
                }
            ]
        }
        results = extract_generic_results(payload, engine="amazon", limit=5)
        self.assertEqual(results[0]["thumbnail"], "https://example.com/item.jpg")
        self.assertEqual(results[0]["extracted_price"], 99.99)
        self.assertTrue(results[0]["prime"])
        self.assertEqual(results[0]["delivery"], ["FREE delivery Wed, Jul 29"])
        self.assertEqual(results[0]["shipping"], "Free shipping")
        self.assertEqual(results[0]["stock"], "Only 8 left in stock")
        self.assertEqual(results[0]["bought_last_month"], "2K+ bought in past month")
        self.assertEqual(results[0]["badges"], ["Overall Pick"])
        self.assertTrue(results[0]["prime_eligible"])

    def test_amazon_product_derives_prime_eligibility_from_delivery_text(self):
        payload = {
            "product_results": {
                "title": "Example Product",
                "asin": "B000TEST3",
                "link": "https://amazon.com/dp/B000TEST3",
                "delivery": [
                    "FREE delivery Sunday",
                    "Or Prime members get FREE delivery Today on eligible orders",
                ],
                "stock": "In Stock",
            }
        }

        results = extract_generic_results(payload, engine="amazon_product", limit=1)

        self.assertIsNone(results[0]["prime"])
        self.assertTrue(results[0]["prime_eligible"])


if __name__ == "__main__":
    unittest.main()
