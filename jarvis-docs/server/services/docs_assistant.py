"""
Docs assistant for the Jarvis Docs viewer: QMD + ripgrep context, then LLM via lib.llm_provider.

Runs on this app (typically :5004). Uses cloud.env / local.env via config_loader.load_config(mode).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

JARVIS_ROOT = Path(__file__).resolve().parents[3]
_DOCS_ROOT = JARVIS_ROOT / "docs"

_search_docs_mod: Any = None

# Lowercase posix path -> canonical path relative to docs/ (for case + alias fixes)
_md_index: dict[str, str] | None = None


def _explorer_relative_path(raw: str) -> str:
    """Docs API ?path= is relative to docs/ only — never include a leading docs/ segment."""
    p = (raw or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    pl = p.lower()
    if pl == "docs":
        return ""
    if pl.startswith("docs/"):
        return p[5:]
    return p


def _build_md_index() -> dict[str, str]:
    global _md_index
    if _md_index is not None:
        return _md_index
    idx: dict[str, str] = {}
    root = _DOCS_ROOT.resolve()
    if not root.is_dir():
        _md_index = idx
        return idx
    for f in root.rglob("*.md"):
        if any(part.startswith(".") for part in f.parts):
            continue
        try:
            rel = f.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        idx[rel.lower()] = rel
    _md_index = idx
    return idx


def _stem_normalized(path_str: str) -> str:
    """Compare stems ignoring case, hyphens, underscores."""
    stem = PurePosixPath(path_str.replace("\\", "/")).stem.lower()
    return stem.replace("-", "").replace("_", "")


def _fuzzy_resolve_doc(rel: str) -> str | None:
    """When QMD/LLM use a hyphenated slug differing from ON-DISK filenames, resolve to one match."""
    if not rel:
        return None
    idx_vals = sorted(set(_build_md_index().values()))
    ns = _stem_normalized(rel)
    want_parent = PurePosixPath(rel.replace("\\", "/")).parent.as_posix()
    folder_match: str | None = None
    fallback: str | None = None
    for canon in idx_vals:
        if _stem_normalized(canon) != ns:
            continue
        canon_parent = PurePosixPath(canon).parent.as_posix()
        if want_parent == canon_parent:
            folder_match = canon
            break
        fallback = canon
    return folder_match or fallback


def _canonical_doc_path(hint: str) -> str:
    """
    Normalize to a path the Docs explorer accepts: relative to docs/, real file on disk.
    Strips accidental docs/ prefix; fixes case when the index or QMD uses a different case.
    """
    rel = _explorer_relative_path(hint)
    if not rel:
        return rel
    root = _DOCS_ROOT.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    except ValueError:
        pass
    key = PurePosixPath(rel.replace("\\", "/")).as_posix().lower()
    idx = _build_md_index()
    if key in idx:
        return idx[key]
    fuzzy = _fuzzy_resolve_doc(rel)
    if fuzzy:
        return fuzzy
    return rel


def _get_search_docs():
    global _search_docs_mod
    if _search_docs_mod is None:
        path = JARVIS_ROOT / "skills" / "search_docs.py"
        spec = importlib.util.spec_from_file_location("jarvis_search_docs", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load skills/search_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _search_docs_mod = mod
    return _search_docs_mod


def _rg_docs_lines(query: str, max_matches: int = 12) -> list[dict[str, Any]]:
    docs_dir = JARVIS_ROOT / "docs"
    if not docs_dir.is_dir():
        return []
    q = (query or "").strip()
    if len(q) < 2:
        return []
    cmd = [
        "rg",
        "--json",
        "--fixed-strings",
        "--smart-case",
        "--glob",
        "*.md",
        "--max-count",
        str(max(1, max_matches)),
        q,
        str(docs_dir),
    ]
    results: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25, cwd=str(JARVIS_ROOT))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode not in (0, 1):
        return []

    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") != "match":
            continue
        m = data.get("data") or {}
        path_obj = m.get("path") or {}
        ftext = path_obj.get("text") or ""
        if not ftext:
            continue
        try:
            rel = Path(ftext).resolve().relative_to(JARVIS_ROOT)
        except ValueError:
            continue
        lines_data = m.get("lines") or {}
        results.append(
            {
                "path": rel.as_posix(),
                "line": m.get("line_number", 0),
                "excerpt": (lines_data.get("text") or "").strip()[:400],
            }
        )
        if len(results) >= max_matches:
            break
    return results


def _qmd_on_path() -> bool:
    """Optional semantic indexer; clone without QMD still works with ripgrep."""
    return shutil.which("qmd") is not None


def _rg_on_path() -> bool:
    return shutil.which("rg") is not None


def _gather_context(user_query: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (markdown_block, citations, retrieval_meta).
    Skips QMD subprocesses entirely when `qmd` is not installed (per docs/qmd/README.md).
    """
    meta: dict[str, Any] = {
        "qmd_available": _qmd_on_path(),
        "rg_available": _rg_on_path(),
        "semantic_count": 0,
        "grep_count": 0,
        "mode": "unknown",
    }

    semantic: list[dict[str, Any]] = []
    if meta["qmd_available"]:
        try:
            sd = _get_search_docs()
            semantic = sd.run_qmd_vsearch(user_query, limit=10, min_score=0.34)
            if not semantic:
                semantic = sd.run_qmd_search_fallback(user_query, limit=8)
        except Exception:
            semantic = []
            meta["semantic_error"] = True
    else:
        meta["qmd_skipped"] = True

    lines: list[str] = []
    citations: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for r in semantic:
        title = (r.get("title") or "Untitled").strip()
        path = (r.get("path") or "").strip()
        score = float(r.get("score") or 0)
        line_hint = int(r.get("line") or 0)
        body = (r.get("content") or "").strip()
        if not path:
            continue
        canon = _canonical_doc_path(path)
        if not canon:
            continue
        key = f"{canon}:{line_hint}"
        if key in seen_paths:
            continue
        seen_paths.add(key)
        citations.append(
            {
                "path": canon,
                "title": title,
                "line": line_hint,
                "score": score,
                "kind": "semantic",
            }
        )
        label = f"[{len(citations)}] {title}"
        loc = f"`{canon}`" + (f" (line ~{line_hint})" if line_hint else "")
        lines.append(f"### {label}\nSource: {loc}  ·  relevance {score:.0%}\n\n{body[:1200]}")
        meta["semantic_count"] += 1

    words = [w for w in re.split(r"\s+", user_query) if len(w) >= 3][:4]
    rg_query = words[0] if len(words) == 1 else user_query.strip()
    if len(rg_query) >= 2 and meta["rg_available"]:
        rg_hits = _rg_docs_lines(rg_query, max_matches=8)
        for h in rg_hits:
            rp = _canonical_doc_path(h["path"])
            if not rp:
                continue
            lk = f"{rp}:{h['line']}"
            if lk in seen_paths:
                continue
            seen_paths.add(lk)
            citations.append(
                {
                    "path": rp,
                    "title": Path(rp).name,
                    "line": h["line"],
                    "score": None,
                    "kind": "grep",
                }
            )
            lines.append(f"### Grep match in `{rp}` (line {h['line']})\n{h.get('excerpt', '')}")
            if len([c for c in citations if c.get("kind") == "grep"]) >= 5:
                break

    meta["grep_count"] = len([c for c in citations if c.get("kind") == "grep"])

    preamble: list[str] = []
    if not meta["qmd_available"]:
        preamble.append(
            "_**Retrieval:** `qmd` is not on PATH — semantic search is skipped; "
            "using ripgrep when available. Optionally install QMD per `docs/qmd/README.md`._\n\n"
        )
    elif meta.get("semantic_error"):
        preamble.append(
            "_**Retrieval:** QMD semantic search raised an error; continuing with ripgrep/fallback excerpts only._\n\n"
        )

    if not meta["rg_available"] and meta["semantic_count"] == 0:
        preamble.append(
            "_**Warning:** neither `rg` (ripgrep) nor QMD results are available; install "
            "ripgrep for basic search (`apt install ripgrep` / `brew install ripgrep`) "
            "or set up QMD via `docs/qmd/README.md`._\n\n"
        )

    merged = preamble + lines

    if meta["semantic_count"] or meta["grep_count"]:
        if meta["semantic_count"] and meta["grep_count"]:
            meta["mode"] = "qmd+rg"
        elif meta["semantic_count"]:
            meta["mode"] = "qmd"
        elif meta["grep_count"]:
            meta["mode"] = "rg"
    elif merged:
        meta["mode"] = "notes_only"

    if not merged:
        fallback = (
            "_(No excerpts were retrieved — QMD/semantic unavailable or empty query, "
            "and ripgrep found nothing (or ripgrep is missing). Explain this briefly and "
            "suggest verifying `qmd`/`rg` installs or rephrasing. Optional QMD setup: docs/qmd/README.md.)_"
        )
        if not meta["rg_available"] and not meta["qmd_available"]:
            fallback = (
                "_(Neither `qmd` nor `rg` appears to be installed; install ripgrep for basic "
                "search and optionally QMD per docs/qmd/README.md for embeddings.)_"
            )
        meta["mode"] = "none"
        return fallback, [], meta

    block = "\n\n---\n\n".join(merged)
    return block, citations[:24], meta


def _load_system_prompt() -> str:
    prompt_path = JARVIS_ROOT / "jarvis-docs" / "data" / "prompts" / "docs_assistant_system.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8").strip()
    return (
        "You are the Jarvis documentation assistant. Answer using the retrieved excerpts. "
        "If something is not in the excerpts, say so. Use markdown. When citing a file, use "
        "paths relative to the docs folder (e.g. `TOOL_CALLING_SYSTEM.md` or "
        "`personal/SKILL.md`) — never prefix with `docs/`."
    )


def _normalize_messages(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in raw:
        role = (m.get("role") or "").strip().lower()
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if content is None:
            continue
        text = str(content).strip()
        if not text:
            continue
        if len(text) > 32000:
            text = text[:32000] + "\n...[truncated]"
        out.append({"role": role, "content": text})
        if len(out) >= 50:
            break
    return out


def run_docs_assistant(messages: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    sys.path.insert(0, str(JARVIS_ROOT / "lib"))

    from config_loader import load_config  # noqa: WPS433

    load_config(mode)

    from llm_provider import create_configured_provider  # noqa: WPS433

    norm = _normalize_messages(messages)
    if not norm or norm[-1]["role"] != "user":
        return {"ok": False, "error": "messages must include a trailing user entry"}

    last_user = norm[-1]["content"]
    retrieval, citations, retrieval_meta = _gather_context(last_user)
    base_system = _load_system_prompt()
    system = (
        f"{base_system}\n\n## Retrieved excerpts from docs/ (read-only)\n\n{retrieval}\n\n"
        "Prefer facts from these excerpts. Quote short phrases when helpful. "
        "When referencing a file, use paths **relative to the docs folder** only, e.g. "
        "`TOOL_CALLING_SYSTEM.md` or `api/health.md` — do not use a `docs/` prefix."
    )

    provider_type, model_name, provider = create_configured_provider(
        mode=mode,
        disable_server_side_tools=True
    )

    text, _, usage, _ = provider.chat_with_tools(
        messages=norm,
        tools=[],
        system_prompt=system,
        enable_thinking=False,
    )

    err = None
    if text is None:
        text = ""
    if text.startswith("Error:"):
        err = text
        usage = usage or {}

    return {
        "ok": bool(text) and err is None,
        "message": text or "",
        "citations": citations,
        "provider": provider_type,
        "model": model_name,
        "usage": usage,
        "retrieval": retrieval_meta,
        **({"error": err} if err else {}),
    }
