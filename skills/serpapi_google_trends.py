#!/usr/bin/env python3
"""Jarvis Skill: query-driven Google Trends analysis through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from serpapi_client import (
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_TRENDS_TIMEOUT = 90
DEFAULT_DATE = "now 7-d"
DEFAULT_MAX_RESULTS = 20
DEFAULT_MAX_TIMELINE_POINTS = 60

DATA_TYPE_CODES = {
    "interest_over_time": "TIMESERIES",
    "compared_by_region": "GEO_MAP",
    "interest_by_region": "GEO_MAP_0",
    "related_topics": "RELATED_TOPICS",
    "related_queries": "RELATED_QUERIES",
}
DATA_TYPE_ALIASES = {
    "timeseries": "interest_over_time",
    "time_series": "interest_over_time",
    "trend": "interest_over_time",
    "trends": "interest_over_time",
    "geo_map": "compared_by_region",
    "compare_by_region": "compared_by_region",
    "regional_comparison": "compared_by_region",
    "geo_map_0": "interest_by_region",
    **{name: name for name in DATA_TYPE_CODES},
}
PROPERTY_CODES = {
    "web": "",
    "images": "images",
    "news": "news",
    "shopping": "froogle",
    "youtube": "youtube",
}
REGION_CODES = {
    "country": "COUNTRY",
    "region": "REGION",
    "dma": "DMA",
    "city": "CITY",
}
STANDARD_DATES = {
    "now 1-H",
    "now 4-H",
    "now 1-d",
    "now 7-d",
    "today 1-m",
    "today 3-m",
    "today 12-m",
    "today 5-y",
    "all",
}
STANDARD_DATE_ALIASES = {value.casefold(): value for value in STANDARD_DATES}
CUSTOM_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2})? \d{4}-\d{2}-\d{2}(?:T\d{2})?$"
)
GEO_RE = re.compile(r"^[A-Z0-9-]{1,24}$")
LANGUAGE_RE = re.compile(r"^[a-z]{2}$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "data_type",
    "date",
    "geo",
    "region",
    "hl",
    "tz",
    "cat",
    "gprop",
    "csv",
    "include_low_search_volume",
    "no_cache",
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").removeprefix("+").removesuffix("%")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if number.is_integer() else number


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def normalize_data_type(value: Any) -> str:
    normalized = str(value or "interest_over_time").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    data_type = DATA_TYPE_ALIASES.get(normalized)
    if not data_type:
        raise ValueError(
            "'data_type' must be interest_over_time, compared_by_region, "
            "interest_by_region, related_topics, or related_queries."
        )
    return data_type


def normalize_queries(value: Any, data_type: str) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    queries: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for part in str(raw_value or "").split(","):
            query = " ".join(part.split())
            identity = query.casefold()
            if not query or identity in seen:
                continue
            if len(query) > 100:
                raise ValueError("Each Google Trends query must be 100 characters or fewer.")
            seen.add(identity)
            queries.append(query)

    if not queries:
        raise ValueError("'query' is required.")
    if len(queries) > 5:
        raise ValueError("Google Trends accepts at most 5 queries per request.")
    if data_type == "compared_by_region" and len(queries) < 2:
        raise ValueError("'compared_by_region' requires at least 2 queries.")
    if data_type in {"interest_by_region", "related_topics", "related_queries"} and len(queries) != 1:
        raise ValueError(f"'{data_type}' accepts exactly 1 query.")
    return queries


def normalize_date(value: Any) -> str:
    date = " ".join(str(value or DEFAULT_DATE).split())
    standard_date = STANDARD_DATE_ALIASES.get(date.casefold())
    if standard_date:
        return standard_date
    if CUSTOM_DATE_RE.fullmatch(date):
        return date
    raise ValueError(
        "'date' must be a supported relative window such as now 7-d or today 12-m, "
        "or a custom start/end range in YYYY-MM-DD format."
    )


def normalize_geo(value: Any) -> str | None:
    geo = str(value or "").strip().upper()
    if not geo:
        return None
    if not GEO_RE.fullmatch(geo):
        raise ValueError("'geo' must be a Google Trends location code such as US or US-OR.")
    return geo


def normalize_language(value: Any) -> str | None:
    language = str(value or "").strip().lower()
    if not language:
        return None
    if not LANGUAGE_RE.fullmatch(language):
        raise ValueError("'language' must be a two-letter language code such as en.")
    return language


def normalize_region(value: Any, data_type: str) -> str | None:
    region = str(value or "").strip().lower()
    if not region:
        return None
    if data_type not in {"compared_by_region", "interest_by_region"}:
        raise ValueError("'region' is supported only for regional Google Trends views.")
    if region not in REGION_CODES:
        raise ValueError("'region' must be country, region, dma, or city.")
    return REGION_CODES[region]


def normalize_property(value: Any) -> tuple[str, str | None]:
    search_property = str(value or "web").strip().lower()
    if search_property not in PROPERTY_CODES:
        raise ValueError("'property' must be web, images, news, shopping, or youtube.")
    return search_property, PROPERTY_CODES[search_property] or None


def _sample_evenly(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[-1]]
    indexes = {
        round(index * (len(items) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def extract_interest_over_time(
    payload: dict[str, Any],
    queries: list[str],
    *,
    max_points: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    section = payload.get("interest_over_time")
    section = section if isinstance(section, dict) else {}
    timeline: list[dict[str, Any]] = []
    series_values: dict[str, list[tuple[str | None, int | float]]] = {
        query: [] for query in queries
    }

    for raw_point in _dict_list(section.get("timeline_data")):
        values = []
        for index, raw_value in enumerate(_dict_list(raw_point.get("values"))):
            query = str(raw_value.get("query") or "").strip()
            if not query and index < len(queries):
                query = queries[index]
            extracted = _number(raw_value.get("extracted_value"))
            if extracted is None:
                extracted = _number(raw_value.get("value"))
            value = {
                key: field_value
                for key, field_value in {
                    "query": query or None,
                    "value": raw_value.get("value"),
                    "extracted_value": extracted,
                }.items()
                if field_value not in (None, "")
            }
            if value:
                values.append(value)
            if query and extracted is not None:
                series_values.setdefault(query, []).append((raw_point.get("date"), extracted))
        if not values:
            continue
        timeline.append({
            key: field_value
            for key, field_value in {
                "date": raw_point.get("date"),
                "timestamp": raw_point.get("timestamp"),
                "values": values,
            }.items()
            if field_value not in (None, "", [])
        })

    averages = []
    averages_by_query: dict[str, int | float] = {}
    for index, item in enumerate(_dict_list(section.get("averages"))):
        query = str(item.get("query") or "").strip()
        if not query and index < len(queries):
            query = queries[index]
        average = _number(item.get("value"))
        if not query or average is None:
            continue
        averages.append({"query": query, "value": average})
        averages_by_query[query] = average

    summaries = []
    for query in queries:
        points = series_values.get(query) or []
        if not points:
            continue
        first_date, first_value = points[0]
        latest_date, latest_value = points[-1]
        previous_value = points[-2][1] if len(points) > 1 else None
        peak_date, peak_value = max(points, key=lambda item: item[1])
        change = latest_value - previous_value if previous_value is not None else None
        period_change = latest_value - first_value
        average_value = averages_by_query.get(query)
        if average_value is None:
            average_value = round(sum(value for _, value in points) / len(points), 1)
        direction = "flat"
        if change is not None and change > 0:
            direction = "rising"
        elif change is not None and change < 0:
            direction = "falling"
        summaries.append({
            "title": query,
            "query": query,
            "latest_date": latest_date,
            "latest_value": latest_value,
            "previous_value": previous_value,
            "change_from_previous": change,
            "change_over_period": period_change,
            "direction": direction,
            "average_value": average_value,
            "peak_value": peak_value,
            "peak_date": peak_date,
            "points_count": len(points),
            "first_date": first_date,
            "first_value": first_value,
        })

    return _sample_evenly(timeline, max_points), summaries, averages, len(timeline)


def extract_region_results(
    payload: dict[str, Any],
    data_type: str,
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], int]:
    key = (
        "compared_breakdown_by_region"
        if data_type == "compared_by_region"
        else "interest_by_region"
    )
    raw_results = _dict_list(payload.get(key))
    results = []
    for item in raw_results[:max_results]:
        location = str(item.get("location") or item.get("geo") or "").strip()
        if not location:
            continue
        result: dict[str, Any] = {
            "title": location,
            "location": location,
            "geo": item.get("geo"),
        }
        if data_type == "compared_by_region":
            values = []
            for value in _dict_list(item.get("values")):
                extracted = _number(value.get("extracted_value"))
                if extracted is None:
                    extracted = _number(str(value.get("value") or "").rstrip("%"))
                values.append({
                    key: field_value
                    for key, field_value in {
                        "query": value.get("query"),
                        "value": value.get("value"),
                        "extracted_value": extracted,
                    }.items()
                    if field_value not in (None, "")
                })
            values = [value for value in values if value]
            if values:
                top = max(values, key=lambda value: value.get("extracted_value", -1))
                result.update({
                    "values": values,
                    "top_query": top.get("query"),
                    "top_value": top.get("extracted_value"),
                })
        else:
            extracted = _number(item.get("extracted_value"))
            if extracted is None:
                extracted = _number(item.get("value"))
            result.update({
                "value": item.get("value"),
                "extracted_value": extracted,
            })
        results.append(result)
    return results, len(raw_results)


def extract_related_results(
    payload: dict[str, Any],
    data_type: str,
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    key = "related_topics" if data_type == "related_topics" else "related_queries"
    section = payload.get(key)
    section = section if isinstance(section, dict) else {}
    raw_rising = _dict_list(section.get("rising"))
    raw_top = _dict_list(section.get("top"))

    def normalize(items: list[dict[str, Any]], trend_type: str) -> list[dict[str, Any]]:
        normalized = []
        for item in items[:max_results]:
            topic = item.get("topic") if isinstance(item.get("topic"), dict) else {}
            title = topic.get("title") if topic else item.get("query")
            if not title:
                continue
            normalized.append({
                key: field_value
                for key, field_value in {
                    "title": title,
                    "query": item.get("query"),
                    "topic_id": topic.get("value"),
                    "topic_type": topic.get("type"),
                    "trend_type": trend_type,
                    "value": item.get("value"),
                    "extracted_value": _number(item.get("extracted_value")),
                    "url": item.get("link"),
                }.items()
                if field_value not in (None, "")
            })
        return normalized

    rising = normalize(raw_rising, "rising")
    top = normalize(raw_top, "top")
    combined = []
    seen: set[str] = set()
    for item in [*rising, *top]:
        identity = str(item.get("topic_id") or item.get("query") or item.get("title") or "").casefold()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        combined.append(item)
        if len(combined) >= max_results:
            break
    return combined, rising, top, len(raw_rising) + len(raw_top)


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
            "google_trends_url",
        )
        if metadata.get(key) not in (None, "")
    }


def _google_trends_request(params: dict[str, Any]) -> dict[str, Any]:
    # proxy_policy=off keeps normal calls direct. The shared request path stays
    # proxy-capable so changing the manifest policy requires no code rewrite.
    return request_serpapi(
        params,
        timeout=GOOGLE_TRENDS_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def build_speech(
    queries: list[str],
    data_type: str,
    results: list[dict[str, Any]],
    date: str,
) -> str:
    query_label = ", ".join(queries)
    if not results:
        return f"Google Trends returned no {data_type.replace('_', ' ')} data for {query_label}."
    if data_type == "interest_over_time":
        leader = max(results, key=lambda item: item.get("latest_value", -1))
        return (
            f"Analyzed Google Trends interest for {query_label} over {date}. "
            f"{leader['query']} has the highest latest interest value at {leader['latest_value']}."
        )
    if data_type in {"compared_by_region", "interest_by_region"}:
        first = results[0]
        return (
            f"Found Google Trends regional interest for {query_label} over {date}. "
            f"Top returned location: {first['location']}."
        )
    rising = next((item for item in results if item.get("trend_type") == "rising"), results[0])
    return (
        f"Found {len(results)} Google Trends {data_type.replace('_', ' ')} result(s) "
        f"for {query_label}. Top rising result: {rising['title']}."
    )


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        data_type = normalize_data_type(input_data.get("data_type"))
        queries = normalize_queries(input_data.get("query"), data_type)
        date = normalize_date(input_data.get("date"))
        geo = normalize_geo(input_data.get("geo"))
        language = normalize_language(input_data.get("language"))
        region = normalize_region(input_data.get("region"), data_type)
        search_property, gprop = normalize_property(input_data.get("property"))
        timezone_offset = _bounded_int(
            input_data.get("timezone_offset"),
            "timezone_offset",
            default=420,
            minimum=-1439,
            maximum=1439,
        )
        category = _bounded_int(
            input_data.get("category"),
            "category",
            default=0,
            minimum=0,
            maximum=9999,
        )
        max_results = _bounded_int(
            input_data.get("max_results"),
            "max_results",
            default=DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=50,
        )
        max_timeline_points = _bounded_int(
            input_data.get("max_timeline_points"),
            "max_timeline_points",
            default=DEFAULT_MAX_TIMELINE_POINTS,
            minimum=1,
            maximum=200,
        )
        include_low_search_volume = parse_bool(
            input_data.get("include_low_search_volume", False)
        )
        if include_low_search_volume and data_type not in {
            "compared_by_region",
            "interest_by_region",
        }:
            raise ValueError(
                "'include_low_search_volume' is supported only for regional Google Trends views."
            )
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        extra_params = input_data.get("extra_params") or {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_trends",
            "q": ",".join(queries),
            "data_type": DATA_TYPE_CODES[data_type],
            "date": date,
            "tz": timezone_offset,
            "cat": category,
            "no_cache": "true" if no_cache else "false",
        }
        for key, value in (
            ("geo", geo),
            ("hl", language),
            ("region", region),
            ("gprop", gprop),
        ):
            if value not in (None, ""):
                params[key] = value
        if include_low_search_volume:
            params["include_low_search_volume"] = "true"
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _google_trends_request(params)
        provider_results_count = 0
        timeline_data: list[dict[str, Any]] = []
        averages: list[dict[str, Any]] = []
        rising: list[dict[str, Any]] = []
        top: list[dict[str, Any]] = []

        if data_type == "interest_over_time":
            timeline_data, results, averages, provider_results_count = extract_interest_over_time(
                payload,
                queries,
                max_points=max_timeline_points,
            )
        elif data_type in {"compared_by_region", "interest_by_region"}:
            results, provider_results_count = extract_region_results(
                payload,
                data_type,
                max_results=max_results,
            )
        else:
            results, rising, top, provider_results_count = extract_related_results(
                payload,
                data_type,
                max_results=max_results,
            )

        metadata = _search_metadata(payload)
        provider_parameters = payload.get("search_parameters")
        provider_parameters = provider_parameters if isinstance(provider_parameters, dict) else {}
        data: dict[str, Any] = {
            "engine": "google_trends",
            "query": ", ".join(queries),
            "queries": queries,
            "data_type": data_type,
            "provider_data_type": DATA_TYPE_CODES[data_type],
            "date": provider_parameters.get("date") or date,
            "geo": provider_parameters.get("geo") or geo or "Worldwide",
            "region": region,
            "language": provider_parameters.get("hl") or language,
            "timezone_offset": provider_parameters.get("tz", timezone_offset),
            "category": provider_parameters.get("cat", category),
            "property": search_property,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:10],
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "trends_url": metadata.get("google_trends_url"),
            "serpapi_searches_used": 1,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google Trends",
        }
        if timeline_data:
            data.update({
                "timeline_data": timeline_data,
                "timeline_points_returned": len(timeline_data),
                "timeline_points_original": provider_results_count,
                "averages": averages,
                "latest_period": timeline_data[-1].get("date"),
            })
        if rising or top:
            data["rising"] = rising
            data["top"] = top
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(queries, data_type, results, date), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google Trends request timed out.")
            return 1
        return_error(f"SerpApi Google Trends error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
