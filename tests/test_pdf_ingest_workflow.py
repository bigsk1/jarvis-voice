import json
from pathlib import Path
from types import SimpleNamespace

from orchestrator.pipeline_executor import PipelineExecutor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = PROJECT_ROOT / "data" / "workflows" / "pdf_ingest.json"


class WorkflowProvider:
    def chat_with_tools(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Create a retrieval-friendly Intel" in prompt:
            content = """# Docker Commands Cheat Sheet
Source: stash://space_web_pdf_test/f_pdf
Original Filename: docker-cheatsheet.pdf

## Overview
This document is a concise Docker command reference.

## Important Facts
- Container Listing: `docker ps -a` lists all containers.
- Image Listing: `docker images` lists local images.

## Concepts and Definitions
- Container: A runnable isolated workload.

## Procedures or Recommendations
- Cleanup: Confirm targets before removing containers or images.

## Caveats and Verification Notes
- Verify command flags against the installed Docker version.

## Keywords
- docker
- container

## Source References
- Original PDF: stash://space_web_pdf_test/f_pdf
- Extracted text: stash://space_pdf_extract_test/f_text
"""
        else:
            content = """# Docker Commands Cheat Sheet

## At a Glance
A concise Docker command reference.

## Important Facts
- `docker ps -a` lists all containers.

## Key Terms
- Container

## Procedures or Practical Takeaways
- Confirm targets before destructive cleanup.

## Caveats and What to Verify
- Verify flags against the installed Docker version.

## Sources and Artifacts
- Original PDF: stash://space_web_pdf_test/f_pdf
- Extracted text: stash://space_pdf_extract_test/f_text
- Intel: pdf-ingest-test.md
"""
        return (
            content,
            None,
            {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            None,
        )


class RecordingToolExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, tool_name, params):
        self.calls.append((tool_name, params))
        if tool_name == "stash":
            return {
                "ok": True,
                "speech": "saved",
                "data": {
                    "ref": "stash://space_remote_test/f_pdf",
                    "space_id": "space_remote_test",
                    "file_id": "f_pdf",
                    "size_bytes": 1234,
                },
            }
        if tool_name == "pdf_read":
            text = (
                "--- Page 1 ---\nDocker Commands Cheat Sheet\n"
                "docker ps lists running containers. " * 8
            )
            return {
                "ok": True,
                "speech": "extracted",
                "data": {
                    "text": text,
                    "page_count": 1,
                    "char_count": len(text),
                    "stash_ref": "stash://space_pdf_extract_test/f_text",
                    "space_id": "space_pdf_extract_test",
                },
            }
        if tool_name == "text_summarizer":
            if params["operation"] == "keywords":
                data = {"keywords": [{"keyword": "docker", "count": 5}]}
            else:
                data = {
                    "summary": "The PDF is a Docker command reference with container and image commands.",
                    "summary_meta": {
                        "summary_method": "llm",
                        "input_characters": 500,
                        "chunk_limited": False,
                    },
                }
            return {"ok": True, "speech": "summarized", "data": data}
        if tool_name == "manage_intel":
            return {
                "ok": True,
                "speech": "created",
                "data": {"file": "pdf-ingest-test.md", "size_bytes": 900},
            }
        if tool_name == "ingest_intel":
            return {
                "ok": True,
                "speech": "ingested",
                "data": {"new_files": 1, "total_facts": 12},
            }
        if tool_name == "canvas":
            return {
                "ok": True,
                "speech": "created",
                "data": {"page_id": "pdf-test", "url": "/canvas/pdf-test"},
            }
        raise AssertionError(f"Unexpected tool: {tool_name}")


def load_workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def run_workflow(query):
    tool_executor = RecordingToolExecutor()
    pipeline = PipelineExecutor(
        mode="cloud",
        executor=SimpleNamespace(
            execute=tool_executor.execute,
            cancel_check=None,
        ),
        provider=WorkflowProvider(),
    )
    result = pipeline.execute(load_workflow(), query)
    return result, tool_executor.calls


def test_attached_pdf_skips_remote_download_and_uses_attachment_stash_ref():
    result, calls = run_workflow(
        """/pdf_ingest

[ATTACHED PDF ARTIFACT]
Filename: docker-cheatsheet.pdf
Stash reference: stash://space_web_pdf_test/f_pdf
MIME type: application/pdf
"""
    )

    assert result["ok"] is True
    assert calls[0][0] == "pdf_read"
    assert calls[0][1]["stash_ref"] == "stash://space_web_pdf_test/f_pdf"
    assert [tool for tool, _params in calls].count("stash") == 0
    assert result["data"]["variables"]["summary_method"] == "llm"
    assert result["data"]["variables"]["summary_chunk_limited"] is False
    assert result["data"]["variables"]["ingest_fact_count"] == 12
    assert result["data"]["variables"]["canvas_page_id"] == "pdf-test"


def test_remote_pdf_is_stashed_then_read_from_normalized_reference():
    result, calls = run_workflow(
        "/pdf_ingest https://example.com/reference/manual.pdf"
    )

    assert result["ok"] is True
    assert calls[0][0] == "stash"
    assert calls[0][1]["kind"] == "url"
    assert calls[0][1]["url"] == "https://example.com/reference/manual.pdf"
    assert calls[1][0] == "pdf_read"
    assert calls[1][1]["stash_ref"] == "stash://space_remote_test/f_pdf"
    assert result["data"]["variables"]["pdf_stash_ref"] == (
        "stash://space_remote_test/f_pdf"
    )
