# Jarvis Docs

Standalone web app for browsing the Jarvis markdown library under **`docs/`** at the repo root: search, sidebar navigation, rendered articles, and an optional **Docs Assistant** chat that answers from retrieved doc excerpts (with citations).

![Jarvis Docs UI](../docs/images/jarvis-docs.jpg)

## Features

- **Reader-first layout**: Section rail, document list/search, Markdown canvas
- **Global search**: Find files and jump to matches across `docs/`
- **Assets**: Repo images referenced from Markdown load via safe paths (`/docs-files/...`)
- **Docs Assistant**: Side panel LLM Q&A grounded in `docs/`; uses **[QMD](../docs/qmd/README.md)** when `qmd` is installed (semantic + keyword), otherwise drops back to **ripgrep** so the UI still runs
- **Optional editing**: Enable in-place Markdown save with **`DOCS_UI_EDIT_ENABLED=true`** (see launcher help)
- **Shared auth**: Respects the same optional web UI token flow as other Jarvis frontends when auth is enabled in config

## Quick start

From the **jarvis-voice** repo root:

```bash
source ~/jarvis-venv/bin/activate   # if you use the standard venv
./bin/jarvis-docs
```

Open **http://localhost:5004** (or your host IP). Custom port: `./bin/jarvis-docs --port 8084`.

## Layout

| Path | Role |
|------|------|
| `client/` | Static UI (`index.html`, CSS, JS) |
| `server/` | Flask app, API routes, Docs Assistant + explorer services |
| `data/prompts/` | Assistant system prompt text |

The server reads Markdown from **`../docs/`** (not from this folder).

## Dependencies

```bash
pip install -r jarvis-docs/requirements.txt
```

Flask + flask-cors; shared helpers come from the parent repo’s `lib/` (loaded at runtime).

## Related docs

- [Main docs index](../docs/README.md) — what lives under `docs/`
- [QMD setup for the assistant](../docs/qmd/README.md) — index `docs/` as the `jarvis-docs` collection for better retrieval
