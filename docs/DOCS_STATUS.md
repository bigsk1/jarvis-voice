# Documentation Status

Last updated: 2026-07-02

This file tracks doc health and maintenance. For the live index, see [README.md](README.md).

---

## Current state

**Tracked docs:** 165 Markdown files under `docs/`: 134 active-tree docs and
31 files under `docs/archive/`. The QMD collection can also include ignored
personal directories present on a particular machine, so its count is not the
tracked-repository count.

**Excluded from QMD index (optional / local-only on disk):**

- `docs/personal/` — gitignored notes
- `docs/samantha-skill/` — gitignored
- `docs/vps2/` — gitignored deployment notes

QMD does not respect `.gitignore`. After `qmd update`, verify private dirs were not re-indexed — see [qmd/README.md](qmd/README.md#excluding-directories).

---

## Pass 1 completed (2026-05-25)

- Fixed broken relative links in `docs/README.md`
- Archive paths for Tool RAG troubleshooting, voice fixes, database deep dive
- Proactive assistant link → `service/PROACTIVE_ASSISTANT_SYSTEM.md`
- Replaced missing `N8N_INTEGRATION.md` → `n8n/n8n-mcp.md`
- Tool counts 54+/50+ → **75+**
- Refreshed `QUICKSTART.md`
- Removed dead cross-links and private path references in public docs
- Re-indexed QMD (public docs only)

---

## Pass 2 completed (2026-05-25)

- xAI: `grok-4.3` default + `grok-build-0.1` documented in `XAI_PROVIDER.md`
- Local Ollama: `qwen3.5:latest` across active docs
- `INSTALL_GUIDE.md` → v2.50.2; `JARVIS_WORKFLOW.md` model tables/footer

---

## Pass 3 completed (2026-05-25)

- **Thinking mode:** Rewrote [EXTENDED_THINKING.md](EXTENDED_THINKING.md) as live guide; moved branch milestones to [archive/thinking/](archive/thinking/)
- **OpenCode phases:** Moved `PHASE1_COMPLETE`, `OPENCODE_PHASE2_*` → [archive/opencode/](archive/opencode/)
- **Proactive Phase 1:** Moved `PHASE_1_COMPLETE.md` → [archive/service/](archive/service/)
- **Deduped:** `archive/PROACTIVE_ASSISTANT_SYSTEM.md` → redirect stub to `service/PROACTIVE_ASSISTANT_SYSTEM.md`
- **Index:** `docs/README.md` updated with historical archive sections; cross-links fixed

---

## Pass 4 completed (2026-05-25)

- **`JARVIS_WORKFLOW.md`** — Added v2.50.x request pipeline (pre-router stack, duplicate guard, continuation, env vars); fixed `MAX_TOOL_TURNS` / retry defaults; tool counts 75+
- **`archive/SEQUENTIAL_THINKING_ARCHITECTURE.md`** — Implementation status banner: planning doc vs live paths (`EXTENDED_THINKING`, intelligence reflection, disabled MCP)
- **`INTELLIGENCE_LAYER.md`** — Correction learning, Profile Card, dashboard port 5003, schema, 8880 API table, CG bridge; fixed `last_outcome` values; removed editorial debris; Grafana → metrics + port 5003 UI
- **`ollama/README.md`** — Verified planning status (2026-05-25); fixed `config_loader.py` line ref

---

## Pass 5 completed (2026-06-29)

- Documented mode as a config/data boundary separate from provider choice.
- Updated README, quick start, install, workflow, Tool Calling, Docker, and
  Windows/macOS guidance for Ollama local models vs cloud-tagged Ollama Cloud.
- Documented strict `cloud` / `local` API validation, task-local scheduled-task
  execution scopes, truthful run provider/model metadata, and mode-explicit Web
  settings reset.
- Removed active-tree broken relative links and repaired the self-contained
  Crawl4AI snapshot's references to pages that were never vendored.
- Replaced removed commands (`prompt-history`, `jarvis-maintenance`,
  `rebuild-fts-index.py`, `start-opencode`, and others) with current entrypoints
  or explicit proposed-command labels.
- Updated current version references to v2.53.0 and current tool-manifest count
  to 78 where an exact count is useful.
- Marked unimplemented OAuth material and superseded implementation plans so
  design text cannot be mistaken for live setup instructions.

Safe validation performed without touching databases, logs, audio, or runtime
stores: relative-link scan, referenced-command/path scan, mode/provider wording
scan, Compose config rendering, shell/Python syntax checks, and the project test
collection boundary.

## Pass 7 completed (2026-07-02)

- Documented **credential-aware tool availability** (section 9 in
  `FUTURE_ENHANCEMENTS.md`): evaluator schema, static-config gates, intentionally
  ungated tools, sync hash vs availability separation.
- Updated `TOOL_MANAGEMENT.md` (enabled vs available, `--mode`, current registry
  flow), `SYNC_ARCHITECTURE.md` (pre-sync filtering, hash scope),
  `TOOL_CALLING_SYSTEM.md`, `skills/README.md` (config_files / webhook_registry).
- Added 2026-07-02 changelog entry in `docs/README.md`; tool-specific notes in
  `docs/tools/ssh/README.md`, `docs/crawl4ai/README.md`,
  `docs/n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md`.

## Pass 6 completed (2026-06-29)

- Moved one-time fix logs, superseded implementation plans, unimplemented
  research, and the original Docker design into topic-preserving paths under
  `docs/archive/`.
- Updated active guides to link to archived design context only where it remains
  useful.
- Repaired relative links inside the moved documents so the archive remains
  browsable and passes the public documentation integrity checks.

## Archived design and fix records

| File | Reason |
|------|--------|
| `archive/api/FIXES_LOG.md` | One-time API fix log; live commands are elsewhere |
| `archive/service/FIXES.md` | November 2025 fix log with obsolete mode/manual-patch details |
| `archive/OAuth/README.md` | Unimplemented provider-auth research proposal |
| `archive/XAI_NATIVE_CONTINUATION_PLAN.md` | Implemented design record; live guide is `XAI_PROVIDER.md` |
| `archive/OPENAI_RESPONSES_ADAPTER_PLAN.md` | Implemented design record; live guide is `OPENAI_PROVIDER.md` |
| `archive/STATUS_UPDATES_DESIGN.md` | Implemented design history; operational values live in env examples |
| `archive/SEQUENTIAL_THINKING_ARCHITECTURE.md` | Explicit unimplemented future design |
| `archive/docker/DOCKER_PLANNING.md` | Original design record; live guide is `docker/README.md` |

Roadmaps such as `FUTURE_ENHANCEMENTS.md`, `ADVANCED_AI_TECHNIQUES.md`,
`JARVIS_PLAYGROUND.md`, `Psychological-Profile-Ideas.md`, and
`swarm/BRAINSTORM.md` remain in the active tree because they are intentionally
future-facing rather than superseded operational guides.

## Remaining maintenance areas

| Area | Action |
|------|--------|
| Third-party snapshots | Refresh intentionally when their pinned version changes; do not silently present them as current upstream docs |
| Exact model pricing/context claims | Re-check provider references before each release because these values drift independently of Jarvis |
| Per-tool examples | Re-check when the corresponding `skills/*.tool.json` contract changes |

---

## Archive policy

Move to `docs/archive/` when a doc is:

- A one-time fix log, test result, or **phase milestone**
- Superseded by a current guide
- A duplicate of a live architecture doc

Archived docs may stay QMD-indexed for search but appear in README only with `(historical)` or under `archive/`.

---

## Maintenance checklist

1. Update the feature doc, not only `docs/README.md` changelog
2. After `qmd update`, verify private dirs not re-indexed if you exclude them
3. Run `qmd embed` when adding new public docs
4. Phase/milestone write-ups → `archive/` with header pointing to live guide
5. Tool count: `find skills -name '*.tool.json' | wc -l` (78 on 2026-06-29)
6. Models: `lib/model_catalog.py` (cloud), `local.env.example` (local)

---

## Related

- [README.md](README.md) — full index
- [qmd/README.md](qmd/README.md) — search index
- [FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md) — roadmap
