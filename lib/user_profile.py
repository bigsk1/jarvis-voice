#!/usr/bin/env python3
"""
User profile card: compact synthesis-only context from jarvis-intel/user_profile.md.

The user_model table stores a cache of the compiled card (text + source hash),
not parallel scalar traits like verbosity/technical_depth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_CARD_HEADING = "## Profile Card"
PROFILE_REFERENCE_HEADING = "## Profile Reference"
DEFAULT_PROFILE_REL_PATH = Path("jarvis-intel") / "user_profile.md"
PROFILE_CARD_CACHE_KEY = "profile_card_cache"
LEARNED_LESSONS_FILE = "jarvis-learned-lessons.md"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_profile_path(root: Path | None = None) -> Path:
    return (root or project_root()) / DEFAULT_PROFILE_REL_PATH


def extract_profile_card(markdown: str) -> str:
    """Return body text under ## Profile Card until the next ## heading."""
    if not markdown:
        return ""

    lines = markdown.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == PROFILE_CARD_HEADING.lower():
            start_idx = idx + 1
            break

    if start_idx is None:
        return ""

    body: list[str] = []
    for line in lines[start_idx:]:
        stripped = line.strip()
        if line.startswith("## ") and stripped.lower() != PROFILE_CARD_HEADING.lower():
            break
        body.append(line)

    return "\n".join(body).strip()


def profile_source_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def load_profile_card_from_disk(path: Path | None = None) -> tuple[str, str, float | None]:
    """
    Read profile card text from disk.

    Returns: (card_text, content_hash, mtime_epoch)
    """
    profile_path = path or default_profile_path()
    if not profile_path.is_file():
        return "", "", None

    raw = profile_path.read_text(encoding="utf-8")
    card = extract_profile_card(raw)
    mtime = profile_path.stat().st_mtime
    return card, profile_source_hash(card), mtime


def _profile_card_enabled() -> bool:
    from config_loader import get_config_value
    return get_config_value("USER_PROFILE_CARD_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def get_cached_profile_card(force_refresh: bool = False, db=None) -> str:
    """
    Return compiled profile card text, using user_model as a cache.

    Cache row key: profile_card_cache (value_type=text).
    """
    if not _profile_card_enabled():
        return ""

    from memory_db import get_memory_db

    owns_db = db is None
    if db is None:
        db = get_memory_db()
    try:
        profile_path = default_profile_path()
        card_text, source_hash, mtime = load_profile_card_from_disk(profile_path)
        if not card_text:
            return ""

        cached = db.get_user_model_trait(PROFILE_CARD_CACHE_KEY)
        if (
            not force_refresh
            and cached
            and cached.get("value_type") == "text"
            and str(cached.get("value", "")).strip()
        ):
            metadata = cached.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            if metadata.get("source_hash") == source_hash:
                return str(cached["value"]).strip()

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            source_path = str(profile_path.relative_to(project_root()))
        except ValueError:
            source_path = str(profile_path)
        metadata = {
            "source_path": source_path,
            "source_hash": source_hash,
            "source_mtime": mtime,
            "compiled_from": profile_path.name,
        }
        db.upsert_user_model_trait(
            PROFILE_CARD_CACHE_KEY,
            card_text,
            value_type="text",
            confidence=1.0,
            source="user_profile.md",
            metadata=metadata,
            last_reconciled_at=now_iso,
        )
        return card_text
    finally:
        if owns_db:
            db.close()


def format_profile_card_prompt_section(card_text: str) -> str:
    card_text = (card_text or "").strip()
    if not card_text:
        return ""
    return (
        "USER PROFILE CARD (synthesis only; runtime env/response_style/explicit prefs win on conflict):\n"
        f"{card_text}"
    )


ROUTER_PROFILE_BOUNDARY = (
    "USER PROFILE CARD\n"
    "Apply for direct-text answers and for tool choice/arguments when the card gives relevant "
    "constraints (e.g. research before changes, ask before destructive actions).\n"
    "Does not affect Tool RAG retrieval — only this routing LLM system prompt.\n"
    "Runtime env (LLM_PROVIDER, JARVIS_RESPONSE_STYLE), model overrides, and explicit pinned prefs win on conflict."
)


def format_router_direct_answer_profile_section(card_text: str) -> str:
    card_text = (card_text or "").strip()
    if not card_text:
        return ""
    return f"{ROUTER_PROFILE_BOUNDARY}\n\n{card_text}"


def append_user_profile_card_to_prompt(base_prompt: str) -> str:
    """Append cached profile card to a synthesis/QA system prompt."""
    base_prompt = base_prompt or ""
    card_text = get_cached_profile_card()
    section = format_profile_card_prompt_section(card_text)
    if not section:
        return base_prompt
    if section in base_prompt:
        return base_prompt
    if base_prompt.strip():
        return f"{base_prompt.rstrip()}\n\n{section}"
    return section


def append_profile_card_for_router_direct_answer(base_prompt: str) -> str:
    """
    Append profile card to the router system prompt for direct-text answers.

    Covers detailed mode and no-tool paths that skip ResponseFormatter synthesis.
    Tool-selection turns are instructed to ignore the card.
    """
    base_prompt = base_prompt or ""
    if not _profile_card_enabled():
        return base_prompt
    card_text = get_cached_profile_card()
    section = format_router_direct_answer_profile_section(card_text)
    if not section:
        return base_prompt
    if ROUTER_PROFILE_BOUNDARY in base_prompt and card_text in base_prompt:
        return base_prompt
    if base_prompt.strip():
        return f"{base_prompt.rstrip()}\n\n{section}"
    return section


def _correction_lessons_enabled() -> bool:
    from config_loader import get_config_value
    return get_config_value("USER_CORRECTION_APPEND_LESSONS", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def build_correction_lesson_entry(
    correction_query: str,
    signals: dict,
    previous_experience_id: int,
) -> str:
    categories = ", ".join(signals.get("categories") or []) or "correction"
    preview = (correction_query or "").strip().replace("\n", " ")
    if len(preview) > 220:
        preview = preview[:220] + "..."
    return (
        f"- **Topic**: User correction (experience {previous_experience_id})\n"
        f"- **Lesson**: Boss corrected a prior answer ({categories}): \"{preview}\". "
        "Avoid repeating this failure pattern in similar follow-up tasks."
    )


def append_correction_to_learned_lessons(
    correction_query: str,
    signals: dict,
    previous_experience_id: int,
) -> dict:
    """
    Code-triggered append to jarvis-learned-lessons.md (apply mode only).

    Does not modify user_profile.md.
    """
    if not _correction_lessons_enabled():
        return {"appended": False, "reason": "disabled"}

    root = project_root()
    intel_dir = root / "jarvis-intel"
    if not intel_dir.is_dir():
        return {"appended": False, "reason": "intel_dir_missing"}

    import sys
    skills_dir = str(root / "skills")
    if skills_dir not in sys.path:
        sys.path.insert(0, skills_dir)

    from manage_intel import append_intel_file, auto_ingest
    from memory_db import MemoryDB

    entry = build_correction_lesson_entry(correction_query, signals, previous_experience_id)
    lessons_path = intel_dir / LEARNED_LESSONS_FILE
    experience_marker = f"(experience {previous_experience_id})"
    if lessons_path.is_file():
        existing = lessons_path.read_text(encoding="utf-8")
        if experience_marker in existing:
            return {"appended": False, "reason": "duplicate_experience", "experience_id": previous_experience_id}

    result = append_intel_file(intel_dir, LEARNED_LESSONS_FILE, entry)

    ingest_result = None
    try:
        db = MemoryDB()
        db_path = getattr(db, "db_path", "")
        db.close()
        mode = "local" if "local" in str(db_path) else "cloud"
        ingest_result = auto_ingest(root, mode)
    except Exception as exc:
        logger.warning("Correction lesson appended but ingest failed: %s", exc)

    return {
        "appended": True,
        "file": result.get("file"),
        "ingest": ingest_result,
    }
