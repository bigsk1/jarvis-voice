import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = PROJECT_ROOT / "data" / "workflows"


def _load_workflow(name: str) -> dict:
    return json.loads((WORKFLOWS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _step(workflow: dict, tool: str) -> dict:
    return next(step for step in workflow["steps"] if step["tool"] == tool)


def test_vacation_reconnaissance_is_explicit_location_required_and_crawl_free():
    workflow = _load_workflow("vacation_reconnaissance")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"]["patterns"] == []
    assert workflow["triggers"]["keywords"] == []
    assert workflow["variables"]["request"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["planning_context"] == {
        "from": "query",
        "extract": "location_date_context",
    }
    assert workflow["variables"]["daily_forecast"] == "none"
    assert workflow["variables"]["forecast_days"] == 0
    assert "crawl_url" not in tools
    assert tools.count("serpapi_tripadvisor") == 2
    assert sum(tool.startswith("serpapi_") for tool in tools) == 5

    weather_step = _step(workflow, "weather")
    assert weather_step["params"] == {
        "location": "${planning_context.location}",
        "forecast": True,
        "days": 7,
    }

    for tripadvisor_step in (
        step for step in workflow["steps"] if step["tool"] == "serpapi_tripadvisor"
    ):
        assert "${planning_context.location}" in tripadvisor_step["params"]["query"]
        assert "${request}" not in tripadvisor_step["params"]["query"]
        assert tripadvisor_step["params"]["include_details"] is False
        assert tripadvisor_step["params"]["include_reviews"] is False

    for tool in (
        "serpapi_google_local",
        "serpapi_google_news_light",
        "serpapi_google_images_light",
    ):
        assert _step(workflow, tool)["params"]["location"] == (
            "${planning_context.location}"
        )

    image_step = _step(workflow, "serpapi_google_images_light")
    assert image_step["params"]["stash_after"] is False

    canvas_step = _step(workflow, "canvas")
    assert "Original request: ${request}" in canvas_step["llm_prompt"]
    assert "Resolved location: ${planning_context.location}" in canvas_step["llm_prompt"]
    assert "do not collapse that range" in canvas_step["llm_prompt"]


def test_buying_brief_uses_three_bounded_searches_and_env_localization():
    workflow = _load_workflow("buying_brief")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"]["patterns"] == []
    assert workflow["triggers"]["keywords"] == []
    assert workflow["variables"]["product"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["shipping_postal_code"] == {
        "from": "env",
        "key": "JARVIS_DEFAULT_POSTAL_CODE",
        "default": "",
    }
    assert "crawl_url" not in tools
    assert sum(tool.startswith("serpapi_") for tool in tools) == 3

    shopping_step = _step(workflow, "serpapi_google_shopping_light")
    assert "location" not in shopping_step["params"]
    assert shopping_step["params"]["no_cache"] is False

    amazon_step = _step(workflow, "serpapi_amazon_search")
    assert "delivery_zip" not in amazon_step["params"]
    assert amazon_step["params"]["include_product_details"] is False

    ebay_step = _step(workflow, "serpapi_ebay_search")
    assert ebay_step["params"]["_stpos"] == "${shipping_postal_code}"


def test_local_services_compare_uses_required_service_and_mode_location_defaults():
    workflow = _load_workflow("local_services_compare")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": ["/local_services_compare", "/service_compare"],
        "patterns": [],
        "keywords": [],
    }
    assert workflow["variables"]["service"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert "crawl_url" not in tools
    assert sum(tool.startswith("serpapi_") for tool in tools) == 3

    local_services_step = _step(workflow, "serpapi_google_local_services")
    assert local_services_step["params"] == {
        "query": "${service}",
        "max_results": 5,
        "no_cache": False,
    }
    assert local_services_step["required"] is False
    assert local_services_step["on_fail"] == "continue"

    google_local_step = _step(workflow, "serpapi_google_local")
    assert "location" not in google_local_step["params"]
    assert google_local_step["params"]["max_results"] == 5
    assert google_local_step["params"]["max_ads"] == 0
    assert google_local_step["required"] is True

    yelp_step = _step(workflow, "serpapi_yelp_search")
    assert "find_loc" not in yelp_step["params"]
    assert yelp_step["params"]["include_reviews"] is True
    assert yelp_step["params"]["review_limit"] == 3
    assert yelp_step["params"]["num_results"] == 5
    assert yelp_step["required"] is False
    assert yelp_step["on_fail"] == "continue"


def test_game_brief_uses_structured_sports_with_optional_web_enrichment():
    workflow = _load_workflow("game_brief")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is False
    assert workflow["triggers"] == {
        "explicit": ["/game_brief", "/game_recap", "/sports_brief"],
        "patterns": [],
        "keywords": [],
    }
    assert workflow["variables"]["subject"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["sport"] == {
        "from": "query",
        "extract": "first_words",
        "max_words": 1,
    }
    assert "crawl_url" not in tools
    assert "stash" not in tools

    sports_step = _step(workflow, "serpapi_google_sports")
    assert sports_step["params"] == {
        "query": "latest ${subject} game",
        "sport": "${sport}",
        "entity_type": "game",
        "max_results": 1,
        "no_cache": False,
    }
    assert sports_step["required"] is True

    for optional_tool in (
        "brave_llm_context",
        "mcp_brave_search_brave_web_search",
    ):
        step = _step(workflow, optional_tool)
        assert step["required"] is False
        assert step["on_fail"] == "continue"

    canvas_step = _step(workflow, "canvas")
    assert canvas_step["required"] is True
    assert canvas_step["action"] == "create"
    assert canvas_step["llm_variable_max_chars"] == 30000
    assert canvas_step["llm_output_validation"]["required_patterns"] == [
        "# Game Brief:",
        "## At a Glance",
        "## Game Story",
        "## Key Performers",
        "## Watch or Recap",
        "## Sources and Confidence",
    ]


def test_night_out_uses_explicit_or_mode_default_location_without_generic_images():
    workflow = _load_workflow("night_out")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": ["/night_out", "/date_night"],
        "patterns": [],
        "keywords": [],
    }
    assert workflow["variables"]["request"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["planning_context"] == {
        "from": "query",
        "extract": "location_date_context",
        "allow_default_location": True,
        "forecast_horizon_days": 10,
    }
    assert "crawl_url" not in tools
    assert "stash" not in tools
    assert "serpapi_google_images_light" not in tools

    weather_step = _step(workflow, "weather")
    assert weather_step["params"] == {
        "location": "${planning_context.location}",
        "forecast": True,
        "days": 10,
    }
    assert weather_step["condition"] == {
        "op": "eq",
        "left": "${planning_context.forecast_eligible}",
        "right": True,
    }
    assert weather_step["required"] is False
    assert weather_step["on_fail"] == "continue"

    for optional_tool in (
        "serpapi_yelp_search",
        "serpapi_tripadvisor",
    ):
        step = _step(workflow, optional_tool)
        assert step["required"] is False
        assert step["on_fail"] == "continue"

    tripadvisor_step = _step(workflow, "serpapi_tripadvisor")
    assert (
        tripadvisor_step["params"]["query"]
        == "things to do in ${planning_context.location}"
    )
    assert "${request}" not in tripadvisor_step["params"]["query"]

    canvas_step = _step(workflow, "canvas")
    assert "exact matching date" in canvas_step["llm_prompt"]
    assert "do not assume the outing is today" in canvas_step["llm_prompt"]
    assert "Closes in 23 min" in canvas_step["llm_prompt"]
    assert "current research snapshot that remains usable" in canvas_step["llm_prompt"]
    assert "availability at the planned visit time" in canvas_step["llm_prompt"]
    assert "otherwise keep the candidate" in canvas_step["llm_prompt"]
    assert "future-date recommendations" not in canvas_step["llm_prompt"]
    assert "weather was intentionally skipped" in canvas_step["llm_prompt"]
    assert canvas_step["llm_output_validation"]["required_patterns"] == [
        "# Night Out:",
        "## Request and Location",
        "## Best-Fit Shortlist",
        "## Suggested Plans",
        "## Weather and Timing",
        "## Verification Notes",
        "## Sources",
    ]


def test_trend_reality_check_keeps_trending_now_seedless_and_optional():
    workflow = _load_workflow("trend_reality_check")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": ["/trend_reality_check", "/trend_check"],
        "patterns": [],
        "keywords": [],
    }
    assert workflow["variables"]["topic_name"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert "crawl_url" not in tools

    trends_steps = [
        step for step in workflow["steps"] if step["tool"] == "serpapi_google_trends"
    ]
    assert len(trends_steps) == 2
    assert trends_steps[0]["params"]["data_type"] == "interest_over_time"
    assert trends_steps[0]["params"]["date"] == "today 3-m"
    assert trends_steps[0]["required"] is True
    assert trends_steps[1]["params"]["data_type"] == "related_queries"
    assert trends_steps[1]["required"] is False

    trending_step = _step(workflow, "serpapi_google_trending_now")
    assert "query" not in trending_step["params"]
    assert trending_step["params"]["action"] == "trending_now"
    assert trending_step["required"] is False
    assert trending_step["on_fail"] == "continue"

    for optional_tool in (
        "serpapi_google_news_light",
        "serpapi_search_index",
    ):
        step = _step(workflow, optional_tool)
        assert step["required"] is False
        assert step["on_fail"] == "continue"

    canvas_step = _step(workflow, "canvas")
    assert "relative indices" in canvas_step["llm_prompt"]
    assert "seedless US feed" in canvas_step["llm_prompt"]
    assert "provider contamination" in canvas_step["llm_prompt"]
    assert "## Confidence and Caveats" in canvas_step["llm_output_validation"][
        "required_patterns"
    ]


def test_team_outlook_reuses_resolved_team_kgmid_for_optional_views():
    workflow = _load_workflow("team_outlook")
    tools = [step["tool"] for step in workflow["steps"]]

    assert workflow["disable_server_side_tools"] is True
    assert workflow["triggers"] == {
        "explicit": ["/team_outlook", "/season_outlook"],
        "patterns": [],
        "keywords": [],
    }
    assert workflow["variables"]["subject"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["sport"] == {
        "from": "query",
        "extract": "first_words",
        "max_words": 1,
    }
    assert "crawl_url" not in tools
    assert tools.count("serpapi_google_sports") == 3

    sports_steps = [
        step for step in workflow["steps"] if step["tool"] == "serpapi_google_sports"
    ]
    assert sports_steps[0]["params"] == {
        "query": "${subject}",
        "sport": "${sport}",
        "entity_type": "team",
        "tab": "games",
        "max_results": 12,
        "no_cache": False,
    }
    assert sports_steps[0]["extract"]["team_kgmid"] == "kgmid"
    assert sports_steps[0]["required"] is True

    standings_step, players_step = sports_steps[1:]
    assert standings_step["params"]["kgmid"] == "${team_kgmid}"
    assert standings_step["params"]["entity_type"] == "team"
    assert standings_step["params"]["tab"] == "standings"
    assert standings_step["extract"]["selected_standing"] == "selected_standing"
    assert standings_step["extract"]["standings_context"] == "standings_context"
    assert standings_step["required"] is False
    assert standings_step["on_fail"] == "continue"

    assert players_step["params"]["kgmid"] == "${team_kgmid}"
    assert players_step["params"]["entity_type"] == "team"
    assert players_step["params"]["tab"] == "players"
    for step in sports_steps[1:]:
        assert "query" not in step["params"]
        assert step["required"] is False
        assert step["on_fail"] == "continue"

    news_step = _step(workflow, "serpapi_google_news_light")
    assert news_step["required"] is False
    assert news_step["on_fail"] == "continue"

    canvas_step = _step(workflow, "canvas")
    assert "bounded current-centered window" in canvas_step["llm_prompt"]
    assert canvas_step["llm_output_validation"]["required_patterns"] == [
        "# Team Outlook:",
        "## Snapshot",
        "## Recent Form",
        "## Upcoming Schedule",
        "## Standings Context",
        "## Roster Context",
        "## Current Storylines",
        "## What Matters Next",
        "## Sources and Limits",
    ]


def test_new_serpapi_workflows_keep_stash_optional_and_canvas_validated():
    for workflow_name in (
        "vacation_reconnaissance",
        "buying_brief",
        "local_services_compare",
    ):
        workflow = _load_workflow(workflow_name)
        stash_step = _step(workflow, "stash")
        canvas_step = _step(workflow, "canvas")

        assert stash_step["required"] is False
        assert stash_step["on_fail"] == "continue"
        assert canvas_step["action"] == "create"
        assert "${run_date}" in canvas_step["params"]["title"]
        assert "${run_time}" in canvas_step["params"]["title"]
        assert canvas_step["llm_variable_max_chars"] == 10000
        assert canvas_step["llm_output_validation"]["required_patterns"]
        assert "${" in canvas_step["llm_output_validation"]["reject_patterns"]
