# Example tool profiles (copy-paste)

These files are **templates only**. Jarvis loads profiles from `skills/profiles/<name>.json` (sibling folder), not from `examples/`.

## Use a profile

1. Copy one file:  
   `cp skills/profiles/examples/<name>.json skills/profiles/<name>.json`
2. Edit overrides if your install has different tools (e.g. extra `mcp_*` names from `./bin/manage-tools.py profile export`).
3. Set in `config/local.env` or `config/cloud.env`:  
   `JARVIS_TOOL_PROFILE=<name>`  
   (use the stem: `memory_and_artifacts`, not the path).
4. Restart Jarvis services, then:  
   `./bin/sync-tools.py local` or `./bin/sync-tools.py cloud`
5. Inspect: `./bin/manage-tools.py profile show`

## Design notes

- **Omitted tools** keep whatever `enabled` is in each `*.tool.json`.
- **Overrides** only list tools this profile turns **off** (or **on** with `true` to force-enable).
- If a tool is already **`"enabled": false`** in its `*.tool.json`, you do **not** need to list it again as `"tool_name": false` in a profile—that is redundant; the tool is already off unless a profile sets it to **`true`**.
- **Unknown names** in `overrides` (e.g. MCP tools you never installed, typos, or tools you deleted) are **ignored** at runtime—no error. Keys only apply when a matching tool is actually registered.
- `canvas` and `stash` are intentionally **not** listed here so they stay on by default; add `"canvas": false` only if you want to hide them.
- `tool_search` and `workflow` are mandatory discovery candidates only while present in the effective registry. A profile can disable either one normally.
- `"workflow": false` disables autonomous workflow discovery/execution through the meta-tool, but does not disable direct `/workflow-name` commands or scheduled workflow tasks.
- After copying, treat the file in `skills/profiles/` as yours. Custom names
  stay gitignored; only the documented ready-to-use baselines and this
  `examples/` tree are tracked.

## Local mode (`local.env` + Ollama)

Files named `local_*.json` target **small-context** setups (often ~32k); the router still uses **ghost tools + about five** semantic retrieves, but the **total number of enabled tools** affects embedding overlap and how confused a small model gets. These profiles assume the machine **still has internet** (not the same as `offline_lan_first.json`). **`analyze_image` is left on** everywhere below—add `"analyze_image": false` only if your local stack has no vision model.

## Bundled examples

| File | Intent |
|------|--------|
| `offline_lan_first.json` | Airplane / lab box: drop internet-ish tools; align with `config/offline.json.example`. |
| `memory_and_artifacts.json` | Stored knowledge + canvas/stash; no web stack or generators. |
| `docs_kb_curator.json` | Docs/PDF/bookmarks/intel/`deep_memory_search` + summarizer; still no SerpAPI/MCP/crawl. |
| `research_pipeline.json` | Research chain (`crawl_url`, SerpAPI core search, Brave, supa crawl, PDFs, YouTube transcript); trims dev/ops and niche SerpAPI. |
| `workstation_ops.json` | Shell/SSH/Docker/monitoring/OpenCode; trims web search and media. |
| `creative_media_lab.json` | Image/video/music + YouTube helpers + stash/canvas; leaves `serpapi_youtube` on for video lookup. |
| `home_routines.json` | Reminders, alerts, weather, speaker, memory, canvas/stash; no research/ops/generation stack. |
| `local_minimal_assistant.json` | Tight general pool: SerpAPI “web” search stays on; niche SerpAPI, Playwright, OpenCode, generators, supa crawl, Spotify, screenshot_url off. |
| `local_daily_driver.json` | Like minimal but leaves **Spotify** and **screenshot_url** on if your `.tool.json` already enables them—still drops OpenCode, gens, Playwright, supa. |
| `local_research_lite.json` | Slim research: crawl + search + summarizer + docs paths; ops tools off. |
| `local_terminal_ops.json` | SSH/docker/monitor/network/bash focus; broad web research tools off. |
| `local_home_voice.json` | Room/voice: reminders, weather, logs, vision; MCP browse + crawl + niche SerpAPI off; core `serpapi_search` can stay on via tool file if you want quick facts. |
