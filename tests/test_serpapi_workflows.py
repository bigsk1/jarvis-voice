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
    assert workflow["variables"]["location"] == {
        "from": "query",
        "extract": "main_subject",
    }
    assert workflow["variables"]["daily_forecast"] == "none"
    assert workflow["variables"]["forecast_days"] == 0
    assert "crawl_url" not in tools
    assert tools.count("serpapi_tripadvisor") == 2
    assert sum(tool.startswith("serpapi_") for tool in tools) == 5

    weather_step = _step(workflow, "weather")
    assert weather_step["params"] == {
        "location": "${location}",
        "forecast": True,
        "days": 7,
    }

    for tripadvisor_step in (
        step for step in workflow["steps"] if step["tool"] == "serpapi_tripadvisor"
    ):
        assert tripadvisor_step["params"]["include_details"] is False
        assert tripadvisor_step["params"]["include_reviews"] is False

    image_step = _step(workflow, "serpapi_google_images_light")
    assert image_step["params"]["stash_after"] is False


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


def test_new_serpapi_workflows_keep_stash_optional_and_canvas_validated():
    for workflow_name in ("vacation_reconnaissance", "buying_brief"):
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
