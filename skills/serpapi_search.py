#!/usr/bin/env python3
"""
Jarvis Skill: SerpApi Search
Generic SerpApi search tool for Amazon and other engines.

Input examples:
  {"engine": "amazon", "query": "usb c hub"}
  {"engine": "amazon_product", "asin": "B08N5WRWNW"}
  {"engine": "google", "query": "latest ai news"}
"""
import json
import os
import re
import sys
from typing import Any

# Add lib to path for config_loader and http_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import get_config_value, load_config
from http_client import get_proxy_config, http_request


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
RESERVED_KEYS = {
    "engine",
    "api_key",
    "q",
    "k",
    "asin",
    "output",
    "device",
    "page",
    "num",
    "no_cache",
    "amazon_domain",
    "language",
}

AMAZON_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "around", "best", "can", "for", "find", "from",
    "give", "help", "i", "ideas", "in", "into", "is", "it", "looking", "me",
    "my", "of", "on", "please", "recommend", "search", "show", "suggest",
    "that", "the", "to", "under", "want", "with", "you", "your",
}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _extract_results(payload: dict[str, Any], engine: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    if engine == "amazon_product":
        product = payload.get("product_results") or {}
        if product:
            results.append(
                {
                    "title": product.get("title"),
                    "url": product.get("link_clean") or product.get("link"),
                    "asin": product.get("asin"),
                    "price": product.get("price"),
                    "rating": product.get("rating"),
                    "reviews": product.get("reviews"),
                    "source": "product_results",
                }
            )
        return results[:limit]

    candidates = []
    for bucket in ("organic_results", "shopping_results", "news_results", "images_results"):
        values = payload.get(bucket)
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    {
                        "title": item.get("title"),
                        "url": item.get("link") or item.get("link_clean") or item.get("source"),
                        "asin": item.get("asin"),
                        "price": item.get("price"),
                        "rating": item.get("rating"),
                        "reviews": item.get("reviews"),
                        "source": bucket,
                    }
                )

    for item in candidates:
        if not item.get("title") and not item.get("url"):
            continue
        results.append(item)
        if len(results) >= limit:
            break

    return results


def _build_speech(engine: str, query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        if query:
            return f"No results found for '{query}' on SerpApi engine '{engine}'."
        return f"No results found on SerpApi engine '{engine}'."

    top = results[0]
    top_title = (top.get("title") or "top result").strip()
    top_price = top.get("price")
    if top_price:
        return (
            f"Found {len(results)} result(s) on '{engine}'. "
            f"Top result: {top_title}, price {top_price}."
        )
    return f"Found {len(results)} result(s) on '{engine}'. Top result: {top_title}."


def _normalize_amazon_query(query: str) -> str:
    """Convert conversational gift prompts into cleaner Amazon keyword queries."""
    raw = (query or "").strip()
    if not raw:
        return raw

    budget_match = re.search(r"\$\s*\d+(?:\s*-\s*\$\s*\d+)?", raw)
    budget_token = budget_match.group(0).replace(" ", "") if budget_match else ""

    cleaned = re.sub(r"[^a-zA-Z0-9$\- ]+", " ", raw.lower())
    tokens = [t for t in cleaned.split() if t]

    kept: list[str] = []
    for token in tokens:
        if token in AMAZON_QUERY_STOPWORDS:
            continue
        # Keep numbers, budget tokens, and meaningful words
        if len(token) <= 1 and not token.isdigit() and not token.startswith("$"):
            continue
        kept.append(token)

    # Keep order but de-duplicate
    seen = set()
    deduped: list[str] = []
    for token in kept:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)

    # If prompt is still too broad/conversational, fall back to a compact gift query
    if len(deduped) < 3:
        deduped = ["tech", "gift", "ideas"]

    # Try to keep query concise for Amazon relevance
    deduped = deduped[:12]
    normalized = " ".join(deduped).strip()

    if budget_token and budget_token not in normalized:
        normalized = f"{normalized} {budget_token}".strip()

    return normalized or raw


def _fallback_amazon_query(query: str) -> str:
    """Create a broad fallback query when strict natural-language search returns zero."""
    raw = (query or "").lower()
    if not raw:
        return "tech gifts"

    topics = []
    if any(word in raw for word in ("tech", "gadget", "electronics", "programming", "coding")):
        topics.append("tech")
    if any(word in raw for word in ("gaming", "gamer")):
        topics.append("gaming")
    if any(word in raw for word in ("smart home", "home automation")):
        topics.append("smart home")
    if not topics:
        topics.append("gift")

    parts = topics + ["gifts"]

    budget_range = re.search(r"\$\s*(\d+)\s*-\s*\$?\s*(\d+)", raw)
    if budget_range:
        low, high = budget_range.group(1), budget_range.group(2)
        parts.extend(["under", high])
    else:
        budget_single = re.search(r"\$\s*(\d+)", raw)
        if budget_single:
            parts.extend(["under", budget_single.group(1)])

    return " ".join(parts).strip()


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": True, "speech": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result: dict[str, Any] = {"ok": False, "speech": speech, "error": speech}
    if data:
        result["data"] = data
    print(json.dumps(result))


def main() -> int:
    try:
        load_config()

        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        engine = str(input_data.get("engine", "")).strip()
        query = str(input_data.get("query", "")).strip()
        asin = str(input_data.get("asin", "")).strip()
        amazon_domain = str(input_data.get("amazon_domain", "amazon.com")).strip()
        language = str(input_data.get("language", "en_US")).strip()
        device = str(input_data.get("device", "desktop")).strip()
        page = int(input_data.get("page", 1))
        num_results = int(input_data.get("num_results", 5))
        no_cache = _parse_bool(input_data.get("no_cache", False))
        include_raw = _parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params", {}) or {}

        if not engine:
            return_error("Parameter 'engine' is required (example: amazon, amazon_product, google).")
            return 1

        if num_results < 1:
            num_results = 1
        if num_results > 10:
            num_results = 10

        if page < 1:
            page = 1

        api_key = get_config_value("SERP_API_KEY", "").strip()
        if not api_key:
            return_error("SERP_API_KEY is not configured.")
            return 1
        if "YOUR_" in api_key or "REPLACE" in api_key or len(api_key) < 16:
            return_error("SERP_API_KEY appears to be a placeholder or invalid.")
            return 1

        params: dict[str, Any] = {
            "engine": engine,
            "api_key": api_key,
            "output": "json",
            "device": device,
            "page": page,
            "no_cache": "true" if no_cache else "false",
        }

        if query:
            if engine == "amazon":
                params["k"] = query
                params["amazon_domain"] = amazon_domain
                params["language"] = language
            else:
                params["q"] = query

        if asin:
            params["asin"] = asin

        if isinstance(extra_params, dict):
            for key, value in extra_params.items():
                if key in RESERVED_KEYS:
                    continue
                params[key] = value

        if engine == "amazon_product" and not asin and not query:
            return_error("For engine 'amazon_product', provide 'asin' (preferred) or 'query'.")
            return 1

        if engine != "amazon_product" and not query and not asin:
            return_error("Provide at least one of: 'query' or 'asin'.")
            return 1

        response = http_request(
            "GET",
            SERPAPI_ENDPOINT,
            params=params,
            timeout=25,
            use_proxy=True,
            fallback_on_proxy_fail=True,
        )

        if response.status_code >= 400:
            return_error(
                f"SerpApi request failed with HTTP {response.status_code}.",
                data={"status_code": response.status_code},
            )
            return 1

        payload = response.json()

        if payload.get("error"):
            return_error(f"SerpApi error: {payload.get('error')}")
            return 1

        results = _extract_results(payload, engine=engine, limit=num_results)
        query_effective = query
        retried_with_normalized_query = False
        retry_attempted_queries: list[str] = []

        # Amazon search is sensitive to conversational phrasing.
        # If first pass returns zero, retry once with normalized keywords.
        if engine == "amazon" and query and not results:
            retry_candidates = []
            normalized_query = _normalize_amazon_query(query)
            if normalized_query and normalized_query != query:
                retry_candidates.append(normalized_query)

            broad_query = _fallback_amazon_query(query)
            if broad_query and broad_query not in retry_candidates and broad_query != query:
                retry_candidates.append(broad_query)

            for candidate in retry_candidates[:2]:
                retry_params = dict(params)
                retry_params["k"] = candidate
                retry_attempted_queries.append(candidate)
                retry_response = http_request(
                    "GET",
                    SERPAPI_ENDPOINT,
                    params=retry_params,
                    timeout=25,
                    use_proxy=True,
                    fallback_on_proxy_fail=True,
                )
                if retry_response.status_code < 400:
                    retry_payload = retry_response.json()
                    if not retry_payload.get("error"):
                        retry_results = _extract_results(retry_payload, engine=engine, limit=num_results)
                        if retry_results:
                            payload = retry_payload
                            results = retry_results
                            query_effective = candidate
                            retried_with_normalized_query = True
                            break

        speech = _build_speech(engine=engine, query=query, results=results)

        data: dict[str, Any] = {
            "engine": engine,
            "query": query or None,
            "query_effective": query_effective or None,
            "asin": asin or None,
            "results_count": len(results),
            "results": results,
            "search_metadata": payload.get("search_metadata", {}),
            "search_information": payload.get("search_information", {}),
            "proxy_enabled": get_proxy_config() is not None,
            "source": "SerpApi",
            "retried_with_normalized_query": retried_with_normalized_query,
            "retry_attempted_queries": retry_attempted_queries,
        }
        if include_raw:
            data["raw"] = payload

        return_success(speech=speech, data=data)
        return 0

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            return_error("SerpApi request timed out.")
            return 1
        return_error(f"SerpApi tool error: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
