"""Verify the shipped deep-dive workflow consumes canonical crawl results."""

import json
from pathlib import Path

from orchestrator.pipeline_executor import PipelineExecutor

ROOT = Path(__file__).resolve().parents[1]


def test_crawl_step_replaces_query_placeholder_with_page_content_and_source():
    workflow = json.loads((ROOT / "data/workflows/deep_dive.json").read_text())
    step = next(step for step in workflow["steps"] if step["step"] == 4)
    markdown = "# Example Domain\n\nThis domain is for use in documentation examples.\n" * 8
    canonical_url = "https://example.org/documentation"
    variables = {
        "content": "/deep_dive https://example.org/original",
        "url": "https://example.org/original",
        "vision_analysis": "Screenshot analysis remains available.",
    }
    result = {
        "ok": True,
        "data": {
            "count": 1,
            "results": [{
                "url": canonical_url,
                "title": "Example Domain",
                "markdown": markdown,
                "success": True,
            }],
        },
    }

    # This transform is independent of provider/executor state. Use the real
    # method without constructing services, logging or an LLM provider.
    pipeline = PipelineExecutor.__new__(PipelineExecutor)
    pipeline._apply_output_transforms(step, result, variables, step["tool"], "")

    assert variables["content"] == markdown
    assert variables["crawled_url"] == canonical_url
    assert variables["title"] == "Example Domain"
    assert variables["page_content"]["content"] == markdown
    assert variables["page_content"]["url"] == canonical_url
    assert variables["vision_analysis"] == "Screenshot analysis remains available."
