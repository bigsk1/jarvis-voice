# Documentation Status

Last updated: 2026-05-25

This file tracks doc health and maintenance. For the live index, see [README.md](README.md).

---

## Current state

**Indexed docs:** 181 markdown files under `docs/` (via QMD `jarvis-docs` collection; includes personal dirs on disk if present).

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
- **`SEQUENTIAL_THINKING_ARCHITECTURE.md`** — Implementation status banner: planning doc vs live paths (`EXTENDED_THINKING`, intelligence reflection, disabled MCP)
- **`INTELLIGENCE_LAYER.md`** — Correction learning, Profile Card, dashboard port 5003, schema, 8880 API table, CG bridge; fixed `last_outcome` values; removed editorial debris; Grafana → metrics + port 5003 UI
- **`ollama/README.md`** — Verified planning status (2026-05-25); fixed `config_loader.py` line ref

---

## Known stale areas (Pass 5+)

| Area | Action |
|------|--------|
| Remaining phase/milestone docs in active tree | Archive if historical only |
| Per-tool READMEs under `docs/tools/` | Spot-check vs `skills/*.tool.json` |
| Install guide service list | Verify against `bin/start` and systemd units |

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
5. Tool count: `find skills -name '*.tool.json' | wc -l` (~77)
6. Models: `lib/model_catalog.py` (cloud), `local.env.example` (local)

---

## Related

- [README.md](README.md) — full index
- [qmd/README.md](qmd/README.md) — search index
- [FUTURE_ENHANCEMENTS.md](FUTURE_ENHANCEMENTS.md) — roadmap
