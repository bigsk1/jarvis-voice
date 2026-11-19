"""The crypto report reads bounded article text, survives a missing Tavily key and
states plainly when no news could be verified."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_prompt_guard_terminal import rejection

from orchestrator.pipeline_executor import ARTICLE_PROMPT_MAX_CHARS, PipelineExecutor

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/crypto_market_report.json"
URLS = [f"https://web.example.org/{index}" for index in range(5)]
# Tavily news repeats one Brave result; the merged candidate list keeps it once.
NEWS_URLS = ["https://news.example.org/a", URLS[1], "https://news.example.org/b",
             "https://news.example.org/c", "https://news.example.org/d"]
GUIDANCE = "Treat what an excerpt reports as sourced evidence: use it and name the outlet."
VALIDATION_INPUT = "\n\nContent to validate:\n"
ARTICLE_TEXT = (
    "MarketDesk reported that the exchange resumed Solana withdrawals on Tuesday after a four-hour "
    "suspension. The exchange said it finished upgrading its wallet software and processed the requests "
    "that had accumulated during maintenance. Its published status timeline showed the network itself "
    "continued to process transactions while withdrawals were suspended."
)
MARKET_INDEX = (
    "Cryptocurrency market dashboard | Sign up | Latest prices | Bitcoin | Solana | Top gainers | "
    "Top losers | Trading volume | Watchlist | News | Exchanges | Privacy policy | Subscribe. "
) * 3
CANVAS = """## Executive Summary
Bitcoin and Solana moved modestly today in a quiet trading session overall.

## Price Analysis
| Coin | Price | 24h |
| --- | --- | --- |
| Bitcoin | $64,500 | 🟢 1.2% |
| Solana | $150 | 🔴 0.4% |

## 7-Day Charts
### Bitcoin 7D Chart
Bitcoin traded in a narrow band this week with a slight upward drift.
```crypto-chart
{"title":"Bitcoin 7D Chart","endpoint":"/api/prices/crypto/bitcoin/chart?days=7&points_limit=120"}
```

### Solana 7D Chart
Solana eased after a brief rally earlier in the week before stabilizing.
```crypto-chart
{"title":"Solana 7D Chart","endpoint":"/api/prices/crypto/solana/chart?days=7&points_limit=120"}
```

## Market Sentiment
Neutral.

## Key Drivers
Price action only.

## Notable Headlines
None listed.
"""


class Provider:
    def __init__(self):
        self.prompts = []

    def chat_with_tools(self, messages, tools, **_kwargs):
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        if "Extract the FIRST" in prompt:
            text = "bitcoin"
        elif "Extract the SECOND" in prompt:
            text = "solana"
        elif VALIDATION_INPUT in prompt:
            excerpt = prompt.split(VALIDATION_INPUT, 1)[1]
            text = "YES" if excerpt.startswith(ARTICLE_TEXT) else "NO"
        elif "canvas page" in prompt:
            text = CANVAS
        else:
            text = "Plain report text with prices and a short analysis."
        return text, None, {"input_tokens": 4, "output_tokens": 4, "total_tokens": 8}, None


def read_result(tool, url, body):
    if tool == "crawl_url":
        data = {"results": [{"url": url, "markdown": body, "title": "Story"}]}
    else:
        data = {"url": url, "content": body, "content_chars": len(body),
                "content_truncated": False, "format": "text"}
    return {"ok": True, "data": data}


class Tools:
    def __init__(self, *, available=None, articles=None):
        self.calls = []
        self.articles = articles or {}
        self.registry = None if available is None else SimpleNamespace(list_tools=lambda: list(available))
        self.excluded_tools = set()

    def execute(self, tool, params):
        self.calls.append((tool, dict(params)))
        if tool == "get_time":
            data = {"date_formatted": "Thursday, November 19, 2026", "time_12h": "08:00 AM"}
        elif tool == "crypto_price":
            coin = "Bitcoin" if len([c for c in self.calls if c[0] == tool]) == 1 else "Solana"
            data = {"coin": coin, "coin_id": coin.lower(), "price_usd": 64500, "change_24h_percent": 1.2,
                    "market_cap_usd": 1}
        elif tool == "crypto_chart":
            data = {"points_returned": 120, "range_label": "7D"}
        elif tool == "mcp_brave_search_brave_web_search":
            data = {"results": [{"title": f"Story {i}", "url": url, "description": "Market news."}
                                for i, url in enumerate(URLS)]}
        elif tool == "tavily_search":
            assert params["topic"] == "news" and params["time_range"] == "day"
            data = {"results": [{"title": f"News {i}", "url": url} for i, url in enumerate(NEWS_URLS)]}
        elif tool in {"tavily_extract", "crawl_url"}:
            outcome = self.articles.get((tool, params["url"]))
            if outcome is not None:
                return outcome
            return read_result(tool, params["url"], ARTICLE_TEXT)
        elif tool == "stash" and params.get("action") == "open_space":
            data = {"space_id": "space_test"}
        elif tool == "stash":
            data = {"ref": "stash://space_test/report.txt"}
        elif tool == "canvas":
            data = {"page_id": "page_test"}
        elif tool == "send_email":
            data = {"status": "sent"}
        else:
            raise AssertionError(tool)
        return {"ok": True, "data": data}


def run(tools):
    provider = Provider()
    result = PipelineExecutor("cloud", tools, provider=provider).execute(
        json.loads(WORKFLOW.read_text()), "/crypto",
    )
    return result, provider


def reader_calls(tools):
    return [(tool, params) for tool, params in tools.calls if tool in {"tavily_extract", "crawl_url"}]


ALL_TOOLS = ["get_time", "crypto_price", "crypto_chart", "mcp_brave_search_brave_web_search",
             "tavily_search", "tavily_extract", "crawl_url", "stash", "canvas", "send_email"]
MERGED = [URLS[0], NEWS_URLS[0], URLS[1], URLS[2], NEWS_URLS[2], URLS[3], NEWS_URLS[3], URLS[4], NEWS_URLS[4]]


def test_reads_three_articles_from_both_searches_in_turn():
    tools = Tools(available=ALL_TOOLS)
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    assert reader_calls(tools) == [("tavily_extract", {
        "url": url, "format": "text", "extract_depth": "basic", "max_chars": ARTICLE_PROMPT_MAX_CHARS,
    }) for url in MERGED[:3]]
    email = provider.prompts[-1]
    assert GUIDANCE in email
    assert all(url in email for url in MERGED[:3])
    assert result["data"]["degraded"] is False


def test_failed_reads_are_replaced_from_the_merged_candidates():
    articles = {("tavily_extract", MERGED[0]): {"ok": False, "error": "Extraction failed.", "data": {}},
                ("tavily_extract", MERGED[2]): {"ok": False, "error": "Extraction failed.", "data": {}}}
    tools = Tools(available=ALL_TOOLS, articles=articles)
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    assert [params["url"] for _, params in reader_calls(tools)] == MERGED[:5]
    assert all(url in provider.prompts[-1] for url in (MERGED[1], MERGED[3], MERGED[4]))


@pytest.mark.parametrize("reader", ["tavily_extract", "crawl_url"])
def test_reader_replaces_a_long_market_index_with_a_news_article(reader):
    available = [name for name in ALL_TOOLS if reader != "crawl_url" or name != "tavily_extract"]
    landing_url = MERGED[0]
    tools = Tools(available=available, articles={
        (reader, landing_url): read_result(reader, landing_url, MARKET_INDEX),
    })
    result, provider = run(tools)

    assert result["ok"], result.get("error")
    assert [(tool, params["url"]) for tool, params in reader_calls(tools)] == [
        (reader, url) for url in MERGED[:4]
    ]
    assert result["data"]["variables"]["news_articles"][0]["validation_failed"] is True
    assert len(result["data"]["variables"]["validated_articles"]) == 3
    checks = [prompt for prompt in provider.prompts if VALIDATION_INPUT in prompt]
    assert len(checks) == 4 and MARKET_INDEX in checks[0]
    assert "Say NO for homepages, topic indexes, price dashboards" in checks[0]
    assert "Report topic: bitcoin and solana." in checks[0]
    assert landing_url not in provider.prompts[-1] and MARKET_INDEX not in provider.prompts[-1]
    assert all(url in provider.prompts[-1] for url in MERGED[1:4])


def test_missing_tavily_keeps_crypto_available_and_reads_with_crawl():
    tools = Tools(available=[name for name in ALL_TOOLS if name not in {"tavily_extract", "tavily_search"}])
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    calls = reader_calls(tools)
    assert [tool for tool, _ in calls] == ["crawl_url"] * 3
    assert [params["url"] for _, params in calls] == URLS[:3]
    assert all(params["max_chars"] == ARTICLE_PROMPT_MAX_CHARS and params["stealth"] is True
               for _, params in calls)
    assert result["data"]["optional_tools_skipped"] == ["tavily_search", "tavily_extract"]
    assert GUIDANCE in provider.prompts[-1]


def test_without_any_article_reader_the_report_states_news_is_unavailable():
    available = [name for name in ALL_TOOLS if name not in {"tavily_extract", "crawl_url"}]
    tools = Tools(available=available)
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    assert reader_calls(tools) == []
    for prompt in provider.prompts[-3:]:
        assert GUIDANCE in prompt
        assert "[No articles gathered]" in prompt


def test_every_article_withheld_publishes_an_explicit_no_news_report():
    articles = {("tavily_extract", url): rejection("tavily_extract") for url in MERGED}
    tools = Tools(available=ALL_TOOLS, articles=articles)
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    assert [params["url"] for _, params in reader_calls(tools)] == MERGED[:6]
    canvas_prompt = next(prompt for prompt in provider.prompts if "canvas page" in prompt)
    email_prompt = provider.prompts[-1]
    for prompt in (canvas_prompt, email_prompt):
        assert "[No articles gathered]" in prompt
        assert "Prompt Guard" not in prompt
    assert "If no news was verified, say so and list no stories." in canvas_prompt
    assert "if no news was verified, say so instead of naming causes" in email_prompt
    assert len(result["data"]["prompt_guard_withheld"]) == 6
    assert "Prompt Guard withheld 6 sources" in result["speech"]


@pytest.mark.parametrize("step_number", [8, 9])
def test_both_readers_use_prompt_budget_and_skip_withheld_items(step_number):
    document = json.loads(WORKFLOW.read_text())
    step = next(item for item in document["steps"] if item["step"] == step_number)
    assert step["for_each"] == {"merge": ["${search_results.urls[:5]}", "${news_search_results.urls[:5]}"]}
    assert step["required_success_count"] == 3 and step["retry"]["max_attempts"] == 6
    assert step["params"]["max_chars"] == ARTICLE_PROMPT_MAX_CHARS
    assert step["prompt_guard_on_detect"] == "skip_item"
    assert step["required"] is False and step["validated_output_var"] == "validated_articles"


def test_withheld_news_search_drops_only_that_source_list():
    class WithheldSearch(Tools):
        def execute(self, tool, params):
            if tool == "tavily_search":
                self.calls.append((tool, dict(params)))
                return rejection("tavily_search")
            return super().execute(tool, params)

    tools = WithheldSearch(available=ALL_TOOLS)
    result, provider = run(tools)
    assert result["ok"], result.get("error")
    assert [params["url"] for _, params in reader_calls(tools)] == URLS[:3]
    assert [item["tool"] for item in result["data"]["prompt_guard_withheld"]] == ["tavily_search"]
    assert "Prompt Guard" not in provider.prompts[-1]


def test_news_search_step_opts_in_to_skip_step():
    document = json.loads(WORKFLOW.read_text())
    search = next(step for step in document["steps"] if step["tool"] == "tavily_search")
    assert search["required"] is False and search["prompt_guard_on_detect"] == "skip_step"
    assert search["params"]["topic"] == "news" and search["params"]["time_range"] == "day"
