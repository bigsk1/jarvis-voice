import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.pipeline_executor import PipelineExecutor
from skills import serpapi_amazon_search, serpapi_ebay_product
from skills.serpapi_amazon_search import normalize_amazon_product_reference
from skills.serpapi_ebay_product import normalize_ebay_product_reference
from skills.serpapi_google_shopping_light import exact_detail_candidate


ROOT = Path(__file__).resolve().parent.parent


class ReportProvider:
    def chat_with_tools(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Amazon listing verification" in prompt:
            title = "Amazon Listing Check"
            identity = "Identity"
            source = "Source"
        elif "eBay listing verification" in prompt:
            title = "eBay Listing Check"
            identity = "Identity and Condition"
            source = "Source"
        else:
            title = "Shopping Product Check"
            identity = "Identity and Variant"
            source = "Sources"
        content = (
            f"# {title}\n\n## {identity}\n"
            "The returned identity was checked against the request.\n\n"
            "## Decision and Unknowns\nTaxes and final cost remain unknown. "
            "The listed price is a snapshot; the live merchant checkout must confirm "
            "shipping, taxes, stock, seller, and the selected product variant.\n\n"
            f"## {source}\nhttps://example.com/product/1234567890\n"
        )
        return content, None, {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}, None


class ProductTools:
    def __init__(self, *, ambiguous=False):
        self.calls = []
        self.ambiguous = ambiguous

    def execute(self, tool_name, params):
        self.calls.append((tool_name, params))
        if tool_name == "get_time":
            return {
                "ok": True,
                "data": {"date_formatted": "Tuesday, September 29, 2026", "time_12h": "9:00 AM"},
            }
        if tool_name == "serpapi_amazon_search":
            return {
                "ok": True,
                "data": {
                    "asin": "B012345678",
                    "results": [
                        {
                            "title": "Acme Product",
                            "asin": "B012345678",
                            "price": "$99",
                            "url": "https://amazon.com/dp/B012345678",
                        }
                    ],
                    "top_url": "https://amazon.com/dp/B012345678",
                    "delivery_location_source": "configured default",
                },
            }
        if tool_name == "serpapi_ebay_product":
            return {
                "ok": True,
                "data": {
                    "product_id": "123456789012",
                    "results": [
                        {"title": "Acme Product", "url": "https://ebay.com/itm/123456789012"}
                    ],
                    "product_summary": {"title": "Acme Product", "product_id": "123456789012"},
                    "seller_summary": {"name": "Seller"},
                    "top_url": "https://ebay.com/itm/123456789012",
                },
            }
        if tool_name == "serpapi_google_shopping_light":
            candidate = (
                None
                if self.ambiguous
                else {
                    "title": "Acme Quiet 5 Black Headphones",
                    "url": "https://example.com/quiet-5",
                    "immersive_product_page_token": "opaque-token",
                }
            )
            return {
                "ok": True,
                "data": {
                    "exact_detail_candidate": candidate,
                    "exact_detail_match_count": 2 if self.ambiguous else 1,
                },
            }
        if tool_name == "serpapi_google_immersive_product":
            if not params.get("page_token"):
                return {"ok": False, "error": "page_token is required"}
            return {
                "ok": True,
                "data": {
                    "product_summary": {"title": "Acme Quiet 5 Black Headphones"},
                    "stores": [
                        {"name": "Audio Shop", "price": "$99", "url": "https://example.com/quiet-5"}
                    ],
                    "top_url": "https://example.com/quiet-5",
                },
            }
        if tool_name == "canvas":
            return {"ok": True, "data": {"page_id": "page_check", "url": "/canvas/page_check"}}
        raise AssertionError(f"Unexpected tool: {tool_name}")


def run_workflow(workflow_id, request, *, ambiguous=False):
    workflow = json.loads((ROOT / "data" / "workflows" / f"{workflow_id}.json").read_text())
    tools = ProductTools(ambiguous=ambiguous)
    pipeline = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(execute=tools.execute, cancel_check=None),
        provider=ReportProvider(),
    )
    return pipeline.execute(workflow, request), tools.calls


def test_retailer_urls_resolve_to_exact_product_ids_and_domains():
    assert normalize_amazon_product_reference(
        "https://www.amazon.co.uk/Some-Item/dp/B012345678?th=1"
    ) == ("B012345678", "amazon.co.uk")
    assert normalize_ebay_product_reference(
        "https://www.ebay.com/itm/Some-Item/123456789012?var=1"
    ) == ("123456789012", "ebay.com")


def test_detail_tools_send_url_derived_ids_instead_of_full_urls():
    amazon_calls = []
    ebay_calls = []

    def amazon_request(params, **_kwargs):
        amazon_calls.append(dict(params))
        return {
            "product_results": {
                "title": "Acme",
                "asin": "B012345678",
                "link": "https://amazon.co.uk/dp/B012345678",
            }
        }

    def ebay_request(params, **_kwargs):
        ebay_calls.append(dict(params))
        return {
            "product_results": {
                "title": "Acme",
                "product_id": "123456789012",
                "product_link": "https://ebay.com/itm/123456789012",
            }
        }

    with (
        patch.object(
            sys,
            "argv",
            [
                "amazon",
                json.dumps(
                    {"engine": "amazon_product", "asin": "https://www.amazon.co.uk/dp/B012345678"}
                ),
            ],
        ),
        patch.object(serpapi_amazon_search, "load_config"),
        patch.object(serpapi_amazon_search, "get_config_value", return_value=""),
        patch.object(serpapi_amazon_search, "request_serpapi", side_effect=amazon_request),
        redirect_stdout(StringIO()),
    ):
        assert serpapi_amazon_search.main() == 0

    with (
        patch.object(
            sys,
            "argv",
            ["ebay", json.dumps({"product_id": "https://www.ebay.com/itm/123456789012"})],
        ),
        patch.object(serpapi_ebay_product, "load_config"),
        patch.object(serpapi_ebay_product, "request_serpapi", side_effect=ebay_request),
        redirect_stdout(StringIO()),
    ):
        assert serpapi_ebay_product.main() == 0

    assert amazon_calls[0]["asin"] == "B012345678"
    assert amazon_calls[0]["amazon_domain"] == "amazon.co.uk"
    assert ebay_calls[0]["product_id"] == "123456789012"
    assert ebay_calls[0]["ebay_domain"] == "ebay.com"


def test_amazon_and_ebay_workflows_pass_one_exact_listing_reference():
    amazon, amazon_calls = run_workflow(
        "verify_amazon", "/verify_amazon https://www.amazon.com/dp/B012345678"
    )
    ebay, ebay_calls = run_workflow(
        "verify_ebay", "/verify_ebay https://www.ebay.com/itm/123456789012"
    )

    assert amazon["ok"] is True
    assert ebay["ok"] is True
    assert (
        next(params for tool, params in amazon_calls if tool == "serpapi_amazon_search")["engine"]
        == "amazon_product"
    )
    assert next(params for tool, params in ebay_calls if tool == "serpapi_ebay_product")[
        "product_id"
    ].endswith("123456789012")
    assert [tool for tool, _ in amazon_calls].count("serpapi_amazon_search") == 1
    assert [tool for tool, _ in ebay_calls].count("serpapi_ebay_product") == 1
    assert [tool for tool, _ in amazon_calls][-1] == "canvas"
    assert [tool for tool, _ in ebay_calls][-1] == "canvas"


def test_shopping_detail_requires_one_unique_matching_product_token():
    rows = [
        {
            "title": "Acme Quiet 5 Black Headphones",
            "product_id": "black",
            "immersive_product_page_token": "black-token",
        },
        {
            "title": "Acme Quiet 5 White Headphones",
            "product_id": "white",
            "immersive_product_page_token": "white-token",
        },
    ]
    selected, count = exact_detail_candidate("Acme Quiet 5 Black", rows)
    assert selected["immersive_product_page_token"] == "black-token"
    assert count == 1
    selected, count = exact_detail_candidate("Acme Quiet 5", rows)
    assert selected is None
    assert count == 2


def test_shopping_workflow_uses_selected_token_and_aborts_ambiguous_match():
    good, good_calls = run_workflow(
        "verify_shopping", "/verify_shopping Acme Quiet 5 Black Headphones"
    )
    ambiguous, ambiguous_calls = run_workflow(
        "verify_shopping", "/verify_shopping Acme Quiet 5 Headphones", ambiguous=True
    )

    assert good["ok"] is True
    assert (
        next(params for tool, params in good_calls if tool == "serpapi_google_immersive_product")[
            "page_token"
        ]
        == "opaque-token"
    )
    assert ambiguous["ok"] is False
    assert "canvas" not in [tool for tool, _ in ambiguous_calls]
