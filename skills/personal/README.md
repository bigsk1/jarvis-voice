# Personal tools

Put private tool scripts and their `.tool.json` definitions directly in this
folder. They work like shared tools: normal Tool RAG sync picks them up, the Web
tool list includes them, and the existing executor runs them. Tool Builder
continues to write to `skills/auto-tools/`.

Everything here except this README is excluded from Git and Docker build
contexts, including supporting files and subdirectories. A fresh clone has no
personal tools. Back up or copy your private files separately when moving Jarvis.

## Add a tool

Create a script and manifest with the same format as shared tools:

```text
skills/personal/my_private_tool.py
skills/personal/my_private_tool.tool.json
```

The manifest's `script` is relative to the manifest, so use
`"script": "my_private_tool.py"`. Choose a unique `name` across shared, generated,
personal, and MCP tools; this folder is for additional tools, not shared-tool
overrides. Put tool manifests directly in `personal/`, rather than nested folders.

Name ownership is resolved in shared, generated, then personal order (sorted by
filename within each folder), before checking `enabled`. Later definitions with
the same name are skipped with a warning, even if the first definition is
disabled. Runtime discovery, the Web list, and management commands all use that
same owner. Rename a conflicting personal tool to make it available. The `mcp_`
name prefix is reserved for MCP tools.

Write the detailed personal description in the manifest itself. Use specific
names and example requests that help Jarvis identify when to call the tool.
Keep URLs and credentials in your existing ignored config or mode ENV files.
Descriptions still enter Tool RAG and may be sent to the configured embedding
service and LLM; Git exclusion does not make tool execution offline.

Python scripts receive a JSON object as their first command-line argument and
return JSON on stdout, for example:

```json
{"ok": true, "speech": "The private tool completed.", "data": {"status": "ready"}}
```

The executor's working directory remains `skills/`. Resolve supporting files
relative to `Path(__file__).resolve().parent`. If your Python tool needs shared
Jarvis helpers, `Path(__file__).resolve().parents[2] / "lib"` is the helper
directory for a script located directly in `skills/personal/`.

The manifest's `enabled` flag, active tool profile, availability requirements,
permissions, and request/Web blocks work the same way as for shared tools. See
[tool definition format](../README.md#tool-definition-format).

## Sync and use

From the project root, sync the modes you use with the operator environment:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
./bin/manage-tools.py list
```

The sync command intentionally requires the operator environment instead of the
repo `.venv`. Restart running Jarvis processes after adding or changing a tool so
their cached registry reloads. Web's Refresh Tools button alone does not refresh
the runtime registry or Tool RAG embeddings.

Ask for the tool naturally or use `#my_private_tool` in Web. To disable it, set
`enabled` to `false` or run `./bin/manage-tools.py disable my_private_tool`, then
sync and restart. Removing a tool also requires sync so its old Tool RAG row is
disabled.

Docker Compose automatically mounts this folder at `/app/skills/personal` in
every Jarvis service. An empty folder (or just this README) adds no tools. After
adding, changing, or removing a personal tool, run `docker compose restart`:
startup detects manifest changes, syncs Tool RAG for the configured startup
modes, and reloads the running registries. No extra Compose override or manual
sync is needed. Tools still need their dependencies and configuration inside
the container. Private files stay out of the image; see the
[Docker guide](../../docs/docker/README.md#personal-tools) for upgrade details.
