"""Compact Project NOMAD tool data for model context and follow-up turns."""

from __future__ import annotations

from typing import Any


def project_nomad_data(value: Any, *, text_budget: int = 8000, row_limit: int = 8) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in (
        "action", "question", "source", "model", "collection", "query", "status", "rag_online",
        "total", "offset", "limit", "has_more", "start_char", "next_start_char",
        "total_chars", "answer_truncated", "zim_inventory_only", "evidence_note", "note",
        "grounding_status", "inventory", "embedding_model", "score_threshold",
        "external_content_trust",
    ) if key in value}
    for key in ("answer", "text"):
        content = value.get(key)
        if isinstance(content, str):
            result[key] = content[:text_budget]
            if len(content) > text_budget:
                result[f"{key}_context_truncated"] = True
    for key in ("files", "collections", "zims", "models"):
        rows = value.get(key)
        if isinstance(rows, list):
            result[key] = rows[:row_limit]
            if len(rows) > row_limit:
                result[f"{key}_context_omitted"] = len(rows) - row_limit
    passages = value.get("passages")
    if isinstance(passages, list):
        selected = passages[:row_limit]
        per_passage = max(0, text_budget // max(1, len(selected)))
        result["passages"] = []
        for row in selected:
            if not isinstance(row, dict):
                continue
            projected = {key: row[key] for key in (
                "full_title", "archive_title", "article_path", "source", "chunk_index",
                "score", "text_truncated",
            ) if key in row}
            content = row.get("text")
            if isinstance(content, str):
                projected["text"] = content[:per_passage]
                if len(content) > per_passage:
                    projected["context_text_truncated"] = True
                    result["passages_context_truncated"] = True
            result["passages"].append(projected)
        if len(passages) > row_limit:
            result["passages_context_omitted"] = len(passages) - row_limit
    return result
