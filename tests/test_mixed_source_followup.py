"""Source identity survives repeated reads and saved conversation replay."""

import importlib.util
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


followup = _load_module(
    "mixed_source_followup",
    ROOT / "jarvis-web/server/services/followup_extractor.py",
)
context = _load_module("mixed_source_context", ROOT / "orchestrator/context_assembler.py")


def _source_run(tool, number, *, enveloped=False):
    source = f"stash://uploads/source_{number}"
    output = f"stash://processed/result_{number}"
    if tool == "pdf_read":
        payload = {
            "text": f"PDF {number}: agreed price $100.",
            "page_count": 2,
            "stash_ref": output,
        }
        arguments = {"action": "extract_text", "stash_ref": source}
    elif tool == "document_ocr":
        payload = {
            "action": "ocr",
            "filename": f"scan-{number}.pdf",
            "markdown_excerpt": f"Scan {number}: payment due in June.",
            "markdown_stash_ref": output,
            "stash_ref": output,
            "pages": [{"page_number": 1}],
        }
        arguments = {"action": "ocr", "stash_ref": source}
    elif tool == "transcribe_audio":
        payload = {
            "source_filename": f"recording-{number}.mp3",
            "source_stash_ref": source,
            "transcript": f"Recording {number}: delivery was delayed.",
            "transcript_stash_ref": output,
            "stash_ref": output,
        }
        arguments = {"source": source}
    elif tool == "stash":
        payload = {
            "ref": source,
            "name": f"note-{number}.txt",
            "content": f"Note {number}: revised offer.",
        }
        arguments = {"action": "read", "space_id": "uploads", "file_id": f"source_{number}"}
    else:
        payload = {
            "summary": f"Summary {number}: revised offer accepted.",
            "source": {"stash_ref": source, "source": "stash"},
        }
        arguments = {"operation": "summarize", "stash_ref": source}
    trace = {"tool": tool, "ok": True, "arguments": arguments}
    return ({"ok": True, "data": payload} if enveloped else payload), trace


SOURCE_TOOLS = ("pdf_read", "document_ocr", "transcribe_audio", "stash", "text_summarizer")


def _runs(compact):
    return compact.get("summaries", compact.get("results", []))


@pytest.mark.parametrize("tool", SOURCE_TOOLS)
@pytest.mark.parametrize("enveloped", [False, True])
def test_repeated_sources_keep_input_output_pairs_after_save_and_context_replay(
    tmp_path, tool, enveloped
):
    first, first_trace = _source_run(tool, 1, enveloped=enveloped)
    second, second_trace = _source_run(tool, 2, enveloped=enveloped)
    compact = followup.extract_followup_data(
        {
            tool: [first, second],
            "_tool_trace": [
                first_trace,
                {"tool": tool, "ok": False, "arguments": {"stash_ref": "stash://wrong/failed"}},
                second_trace,
            ],
        }
    )

    rows = _runs(compact[tool])
    assert len(rows) == 2
    for index, row in enumerate(rows, 1):
        assert row["source_stash_ref"] == f"stash://uploads/source_{index}"
        assert row["request"] == [first_trace, second_trace][index - 1]["arguments"]
        if tool in {"pdf_read", "document_ocr", "transcribe_audio"}:
            assert row["stash_ref"] == f"stash://processed/result_{index}"
        if tool == "transcribe_audio":
            assert row["transcript_stash_ref"] == f"stash://processed/result_{index}"
            assert f"Recording {index}:" in row["transcript_excerpt"]
    assert "stash://wrong/failed" not in json.dumps(compact)

    saved = tmp_path / "conversation.json"
    saved.write_text(
        json.dumps(
            [
                {
                    "role": "assistant",
                    "content": "Compared the sources.",
                    "tools_used": [tool],
                    "tool_results": compact,
                }
            ]
        )
    )
    assembler = context.ContextAssembler.__new__(context.ContextAssembler)
    assembler.timezone = ZoneInfo("UTC")
    assembler._safe_iso_to_local_datetime = lambda _value: None
    rendered = assembler.format_conversation_context(
        "What did the second source say?", json.loads(saved.read_text())
    )
    assert "stash://uploads/source_1" in rendered
    assert "stash://uploads/source_2" in rendered
    assert "source_stash_ref" in rendered
    assert "Structured follow-up data" in rendered


@pytest.mark.parametrize("tool", SOURCE_TOOLS)
def test_all_six_sources_survive_default_ranked_candidate_limit(tool):
    pairs = [_source_run(tool, number) for number in range(1, 7)]
    compact = followup.extract_followup_data(
        {tool: [p[0] for p in pairs], "_tool_trace": [p[1] for p in pairs]}
    )[tool]
    assert len(_runs(compact)) == 6
    assert [row["source_stash_ref"] for row in _runs(compact)] == [
        f"stash://uploads/source_{number}" for number in range(1, 7)
    ]


def test_missing_trace_rows_never_pair_a_source_with_an_unrelated_output():
    first, _ = _source_run("pdf_read", 1)
    second, second_trace = _source_run("pdf_read", 2)
    compact = followup.extract_followup_data(
        {"pdf_read": [first, second], "_tool_trace": [second_trace]}
    )["pdf_read"]
    assert len(compact["results"]) == 2
    assert all("request" not in row and "source_stash_ref" not in row for row in compact["results"])
    assert compact["results"][0]["stash_ref"] == "stash://processed/result_1"


def test_repeated_transcript_previews_share_one_bounded_content_budget():
    pairs = [_source_run("transcribe_audio", number) for number in range(1, 7)]
    for payload, _trace in pairs:
        payload["transcript"] = "Transcript evidence. " * 10000
    compact = followup.extract_followup_data({"transcribe_audio": [p[0] for p in pairs]})[
        "transcribe_audio"
    ]
    rows = compact["results"]
    assert len(rows) == 6
    assert sum(len(row["transcript_excerpt"]) for row in rows) <= 6000
    assert all("truncated for follow-up context" in row["transcript_excerpt"] for row in rows)
    assert all(row["source_stash_ref"] and row["transcript_stash_ref"] for row in rows)


def test_source_runs_over_bound_report_omissions_and_preserve_retained_ref_pairs():
    pairs = [_source_run("pdf_read", number) for number in range(1, 10)]
    compact = followup.extract_followup_data(
        {"pdf_read": [p[0] for p in pairs], "_tool_trace": [p[1] for p in pairs]}
    )["pdf_read"]
    assert compact["runs_count"] == 9
    assert compact["results_truncated"] is True
    assert len(compact["results"]) == 6
    assert compact["results"][0]["source_stash_ref"] == "stash://uploads/source_1"


def test_single_source_preserves_the_existing_compact_shape():
    compact = followup.extract_followup_data(
        {
            "pdf_read": {
                "page_count": 2,
                "text": "Invoice total: $100.",
                "stash_ref": "stash://output/text",
            }
        }
    )
    assert compact == {
        "pdf_read": {
            "page_count": 2,
            "stash_ref": "stash://output/text",
            "text_excerpt": "Invoice total: $100.",
        }
    }


@pytest.mark.parametrize("unsupported", [{}, None, "unstructured result"])
def test_unsupported_source_runs_keep_original_ordinals_without_claiming_cap_truncation(unsupported):
    second, _trace = _source_run("pdf_read", 2)
    compact = followup.extract_followup_data({"pdf_read": [unsupported, second]})["pdf_read"]
    assert compact["runs_count"] == 2
    assert compact["results"][0]["run_ordinal"] == 2
    assert compact["results"][0]["stash_ref"] == "stash://processed/result_2"
    assert compact["unsupported_runs_count"] == 1
    assert compact["unsupported_run_ordinals"] == [1]
    assert not compact.get("results_truncated")


def test_source_cap_and_unsupported_omissions_are_reported_separately():
    runs = [{}, *[_source_run("pdf_read", number)[0] for number in range(2, 9)]]
    compact = followup.extract_followup_data({"pdf_read": runs})["pdf_read"]
    assert [row["run_ordinal"] for row in compact["results"]] == [2, 3, 4, 5, 6]
    assert compact["unsupported_run_ordinals"] == [1]
    assert compact["unsupported_runs_count"] == 1
    assert compact["results_truncated"] is True
    assert compact["truncated_runs_count"] == 2


def test_all_unsupported_source_runs_still_report_the_omission():
    compact = followup.extract_followup_data({"pdf_read": [{}, {}]})["pdf_read"]
    assert compact["results"] == []
    assert compact["unsupported_run_ordinals"] == [1, 2]
    assert compact["unsupported_runs_count"] == compact["runs_count"] == 2
    assert not compact.get("results_truncated")


def test_summarizer_top_level_summary_survives_an_unrelated_data_object():
    result = followup.compact_text_summarizer_item({
        "summary": "The source supports the revised total.",
        "source": {"stash_ref": "stash://uploads/original"},
        "data": {"statistics": {"word_count": 99}},
    })
    assert result["summary"] == "The source supports the revised total."
    assert result["stash_ref"] == "stash://uploads/original"


def _history_assembler():
    assembler = context.ContextAssembler.__new__(context.ContextAssembler)
    assembler.timezone = ZoneInfo("UTC")
    assembler._safe_iso_to_local_datetime = lambda _value: None
    return assembler


def test_all_source_handles_and_note_excerpts_survive_user_prose_truncation():
    references = [f"stash://space_web_text_{number:032x}/f_{number:012x}" for number in range(1, 7)]
    inventory = "\n".join(
        f"Source {index}: {str(index) + 'x' * 195 + '.txt'} (text)\nStash reference: {ref}"
        for index, ref in enumerate(references, 1)
    )
    evidence = "\n".join(
        f"[TEXT CONTENT — Source {index}]\nNOTE_{index}_EVIDENCE " + "text " * 100
        for index in range(1, 7)
    )
    attachment_context = "[ATTACHED SOURCES]\n" + inventory + "\n" + evidence
    assert 2000 < len(attachment_context) < 8000
    rendered = _history_assembler().format_conversation_context(
        "Compare the sixth note with the first.",
        [
            {
                "role": "user",
                "content": "LONG USER PROMPT " * 1000,
                "attachment_context": attachment_context,
            }
        ],
    )
    for index, ref in enumerate(references, 1):
        assert rendered.count(ref) == 1
        assert f"NOTE_{index}_EVIDENCE" in rendered
    assert rendered.count("[ATTACHED SOURCES]") == 1
    assert "LONG USER PROMPT " * 1000 not in rendered


def test_attachment_context_has_its_own_explicit_safety_bound():
    rendered = _history_assembler().format_conversation_context(
        "Follow up",
        [{"role": "user", "content": "Original question", "attachment_context": "A" * 12000}],
    )
    assert "Original question" in rendered
    assert "attachment context truncated" in rendered
    assert "A" * 8001 not in rendered


def test_legacy_user_prose_does_not_gain_an_empty_attachment_block():
    rendered = _history_assembler().format_conversation_context(
        "Follow up",
        [{"role": "user", "content": "Original question"}],
    )
    assert "User: Original question" in rendered
    assert "Attached source context" not in rendered


def test_uploaded_image_metadata_coexists_with_repeated_stash_tool_reads():
    pairs = [_source_run("stash", number) for number in (1, 2)]
    uploaded = {
        "stash_ref": "stash://photos/reference_image",
        "filename": "reference.jpg",
        "tool_origin": "web_upload",
        "has_vision_analysis": True,
        "vision_analysis": "A red label beside the printed price.",
    }
    data = {
        "stash": [payload for payload, _trace in pairs],
        "_tool_trace": [trace for _payload, trace in pairs],
        "_web_upload_stash": {
            **uploaded,
            "uploaded_images": [{**uploaded, "ordinal": 1}],
        },
    }
    compact = followup.extract_followup_data(data)
    assert len(compact["stash"]["results"]) == 2
    for number in (1, 2):
        row = compact["stash"]["results"][number - 1]
        assert row["source_stash_ref"] == f"stash://uploads/source_{number}"
        assert f"Note {number}: revised offer." in row["content_excerpt"]
    assert compact["uploaded_image"]["stash_ref"] == uploaded["stash_ref"]
    assert compact["uploaded_images"][0]["vision_analysis"] == uploaded["vision_analysis"]
    assert "_web_upload_stash" not in compact
    rendered = _history_assembler().format_conversation_context(
        "Compare the second note with the picture.",
        [
            {
                "role": "assistant",
                "content": "Compared the references.",
                "tools_used": ["stash"],
                "tool_results": compact,
            }
        ],
    )
    assert "stash://uploads/source_2" in rendered
    assert uploaded["stash_ref"] in rendered
    assert uploaded["vision_analysis"] in rendered


def test_explicit_upload_metadata_precedes_legacy_upload_alias():
    compact = followup.extract_followup_data(
        {
            "stash": {"stash_ref": "stash://old/image", "tool_origin": "web_upload"},
            "_web_upload_stash": {
                "stash_ref": "stash://current/image",
                "tool_origin": "web_upload",
            },
        }
    )
    assert compact["uploaded_image"]["stash_ref"] == "stash://current/image"
