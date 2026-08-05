"""Status LLM provider-call observability coverage."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import status_llm


def test_openai_status_call_logs_usage_and_correlation_metadata():
    config = {
        "STATUS_LLM_ENABLED": "true",
        "STATUS_LLM_PROVIDER": "openai",
        "STATUS_LLM_MODEL": "gpt-4o-mini",
        "OPENAI_API_KEY": "test-key",
    }
    with (
        patch.object(
            status_llm,
            "get_config_value",
            side_effect=lambda key, default="": config.get(key, default),
        ),
        patch.object(status_llm, "get_int", return_value=30),
    ):
        summarizer = status_llm.StatusSummarizer()

    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {"content": "Checking the latest forecast"}}],
        "usage": {
            "prompt_tokens": 42,
            "completion_tokens": 6,
            "total_tokens": 48,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
    }
    logger = MagicMock()
    metadata = {
        "mode": "cloud",
        "status_task_id": "task-1",
        "status_request_id": 2,
        "status_call_index": 1,
    }

    with (
        patch.object(status_llm.requests, "post", return_value=response),
        patch("llm_logger.get_logger", return_value=logger),
    ):
        result = summarizer.summarize(
            "Getting weather information",
            tool_name="weather",
            call_metadata=metadata,
        )

    assert result == "Checking the latest forecast"
    logged = logger.log_llm_call.call_args.kwargs
    assert logged["prompt_type"] == "status_update"
    assert logged["call_metadata"] == metadata
    assert logged["usage_info"]["input_tokens"] == 42
    assert logged["usage_info"]["output_tokens"] == 6


def test_status_context_truncation_is_explicit_not_empty_fallback():
    empty = status_llm.StatusSummarizer._truncate_context_for_prompt("")
    assert empty == "Working on task"

    short = "Searching for chair reviews"
    assert status_llm.StatusSummarizer._truncate_context_for_prompt(short) == short

    long_context = "x" * 600
    truncated = status_llm.StatusSummarizer._truncate_context_for_prompt(long_context)
    assert truncated.endswith("... [truncated]")
    assert len(truncated) == 500
    assert truncated != "Working on task"


def test_build_prompt_keeps_long_context_with_truncation_marker():
    summarizer = status_llm.StatusSummarizer()
    prompt = summarizer._build_prompt("y" * 600, "serpapi_amazon_search", "progress")
    assert "... [truncated]" in prompt
    assert "Working on task" not in prompt.split("Current state:")[1]


def test_clean_response_strips_exclamation_marks_for_tts():
    summarizer = status_llm.StatusSummarizer()
    assert summarizer._clean_response("Digging for info like a pro!") == (
        "Digging for info like a pro."
    )
