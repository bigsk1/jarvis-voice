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
                    "content_char_count": sum(
                        not character.isspace()
                        for character in text.removeprefix("--- Page 1 ---\n")
                    ),
                    "needs_ocr": False,
                    "extraction_method": "pdf_text",
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


def run_workflow(query, tool_executor=None, available_tools=None):
    tool_executor = tool_executor or RecordingToolExecutor()
    executor = SimpleNamespace(
        execute=tool_executor.execute,
        cancel_check=None,
    )
    if available_tools is not None:
        executor.registry = SimpleNamespace(list_tools=lambda: available_tools)
    pipeline = PipelineExecutor(
        mode="cloud",
        executor=executor,
        provider=WorkflowProvider(),
    )
    result = pipeline.execute(load_workflow(), query)
    return result, tool_executor.calls


class ScannedPdfToolExecutor(RecordingToolExecutor):
    def __init__(self, *, ocr_succeeds=True, ocr_text=None):
        super().__init__()
        self.ocr_succeeds = ocr_succeeds
        self.ocr_text = ocr_text or (
            "# Page 1\nThis scanned manual includes operating instructions, "
            "model specifications, and safety limits."
        )

    def execute(self, tool_name, params):
        if tool_name == "pdf_read":
            self.calls.append((tool_name, params))
            return {
                "ok": True,
                "data": {
                    "text": "--- Page 1 ---\n\n--- Page 2 ---\n\n--- Page 3 ---\n",
                    "page_count": 3,
                    "char_count": 49,
                    "content_char_count": 0,
                    "needs_ocr": True,
                    "extraction_method": "pdf_text",
                    "stash_ref": "stash://space_pdf_extract_test/markers_only",
                    "space_id": "space_pdf_extract_test",
                },
            }
        if tool_name == "document_ocr":
            self.calls.append((tool_name, params))
            if not self.ocr_succeeds:
                return {"ok": False, "error": "OCR service unavailable"}
            return {
                "ok": True,
                "data": {
                    "action": "ocr",
                    "markdown_stash_ref": "stash://space_ocr_test/f_markdown",
                    "json_stash_ref": "stash://space_ocr_test/f_json",
                    "markdown_file_id": "f_markdown",
                    "markdown_char_count": len(self.ocr_text),
                    "space_id": "space_ocr_test",
                },
            }
        if tool_name == "stash" and params.get("action") == "read":
            self.calls.append((tool_name, params))
            if params.get("file_id") != "f_markdown":
                return {"ok": False, "error": "OCR text is unavailable"}
            return {"ok": True, "data": {"content": self.ocr_text}}
        return super().execute(tool_name, params)


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
    manage_params = next(params for tool, params in calls if tool == "manage_intel")
    assert "path" not in manage_params
    assert manage_params["filename_from_title"] is True
    assert manage_params["filename_prefix"] == "pdf-ingest"
    assert manage_params["on_conflict"] == "version"


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


def test_scanned_pdf_uses_ocr_artifact_for_summary_and_provenance():
    result, calls = run_workflow(
        "/pdf_ingest stash://space_web_pdf_test/f_pdf",
        ScannedPdfToolExecutor(),
    )

    assert result["ok"] is True
    assert [tool for tool, _ in calls[:3]] == ["pdf_read", "document_ocr", "stash"]
    assert calls[1][1]["stash_ref"] == "stash://space_web_pdf_test/f_pdf"
    assert calls[2][1]["space_id"] == "space_ocr_test"
    assert calls[2][1]["file_id"] == "f_markdown"
    summaries = [params for tool, params in calls if tool == "text_summarizer"]
    assert summaries
    assert all(params["stash_ref"] == "stash://space_ocr_test/f_markdown" for params in summaries)
    variables = result["data"]["variables"]
    assert variables["extraction_method"] == "ocr"
    assert variables["ocr_json_stash_ref"] == "stash://space_ocr_test/f_json"


def test_scanned_pdf_does_not_summarize_page_markers_when_ocr_fails():
    result, calls = run_workflow(
        "/pdf_ingest stash://space_web_pdf_test/f_pdf",
        ScannedPdfToolExecutor(ocr_succeeds=False),
    )

    assert result["ok"] is False
    assert "text_summarizer" not in [tool for tool, _ in calls]
    assert "manage_intel" not in [tool for tool, _ in calls]


def test_scanned_pdf_does_not_ingest_empty_ocr_text():
    result, calls = run_workflow(
        "/pdf_ingest stash://space_web_pdf_test/f_pdf",
        ScannedPdfToolExecutor(ocr_text="Page 1"),
    )

    assert result["ok"] is False
    assert "text_summarizer" not in [tool for tool, _ in calls]


def test_optional_ocr_availability_does_not_block_searchable_pdfs():
    tool_names = [
        "stash", "pdf_read", "text_summarizer", "manage_intel", "ingest_intel", "canvas"
    ]
    query = "/pdf_ingest stash://space_web_pdf_test/f_pdf"

    digital, digital_calls = run_workflow(query, available_tools=tool_names)
    scanned, scanned_calls = run_workflow(
        query, ScannedPdfToolExecutor(), available_tools=tool_names
    )

    assert digital["ok"] is True
    assert digital["data"]["degraded"] is False
    assert "document_ocr" not in [tool for tool, _ in digital_calls]
    assert scanned["ok"] is False
    assert "document_ocr" not in [tool for tool, _ in scanned_calls]
    assert "text_summarizer" not in [tool for tool, _ in scanned_calls]


def test_pdf_read_ocr_signal_excludes_page_markers(tmp_path):
    import fitz
    from skills import pdf_read

    pdf_path = tmp_path / "scanned.pdf"
    document = fitz.open()
    for _ in range(3):
        document.new_page()
    document.save(pdf_path)
    document.close()

    result = pdf_read.action_extract_text({"file_path": str(pdf_path)})

    assert result["ok"] is True
    assert result["data"]["char_count"] >= 40
    assert result["data"]["content_char_count"] == 0
    assert result["data"]["needs_ocr"] is True


def test_pdf_read_keeps_searchable_pdf_on_text_path(tmp_path):
    import fitz
    from skills import pdf_read

    pdf_path = tmp_path / "text.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "This searchable PDF has enough real content for an ordinary summary and keyword extraction.")
    document.save(pdf_path)
    document.close()

    result = pdf_read.action_extract_text({"file_path": str(pdf_path)})

    assert result["data"]["content_char_count"] >= 40
    assert result["data"]["needs_ocr"] is False
