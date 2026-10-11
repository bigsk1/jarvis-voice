---
name: jarvis-craft-tools
description: Install, connect, update and troubleshoot the optional Jarvis Craft Gateway and its image, PDF, photo, video and motion tools on a local or remote processing host.
---

# Jarvis Craft Tools setup

Read [README.md](README.md) for prerequisites and the setup path matching the
user's host. This folder is a standalone gateway package within Jarvis Voice;
its `setup.sh` installs native upstream releases and our HTTP adapter. Upstream
CLI/stdio MCP servers alone do not provide the configured HTTP API. The browser
portal is optional and separate from native processing.

Determine the processing host, Jarvis client location, selected cloud/local
mode, existing app paths, and connection method from the session and live host.
Inspect existing services and ports before selecting a listener. Use the
provided setup script, configurable roots and port; do not introduce a personal
hostname or reuse someone else's credentials. Initially the gateway host needs
Linux x86_64 and Python 3.12+; clients need network access, not native Craft binaries.

Track the working directory separately on each host. Inside a copied
`jarvis-craft-tools/` folder, invoke `./setup.sh`; from a full checkout root,
invoke `./jarvis-craft-tools/setup.sh`. Run client configuration and probing
from the Jarvis client's checkout root using
`python3 jarvis-craft-tools/scripts/configure_jarvis.py` and
`python3 jarvis-craft-tools/scripts/probe.py`. Do not reuse the processing
host's relative script paths on the client.

- New install: run `setup.sh` on the processing host. It downloads checksum-locked
  native releases, installs hash-locked gateway dependencies in an isolated venv,
  and generates a private API key. Use `--apps` for a subset.
- Existing app installation: use `--skip-app-install --apps-root PATH`. Inspect
  capabilities: unmanaged or untested versions are not enabled automatically.
- Native same-host client: loopback HTTP on the configured unprivileged port.
- Remote client: use `--bind ADDRESS --tls-host DNS_OR_IP` or a Unix socket behind
  an existing HTTPS proxy. Bind only the intended interface. Trust the public
  CA on the client; never disable verification or copy CA/server private keys.
- Use `--start` only when starting the authorized user service. Keep the gateway
  separate from Jarvis. User-service boot persistence may require linger.

`jarvis-client.env` and `gateway.json` are private host-side files. Transfer
settings securely, never print tokens into tool output, conversation, reports
or version control. `scripts/configure_jarvis.py` copies settings into exactly
one selected mode ENV without displaying them. A remote CA path must be changed
to its client-side path; Docker needs that certificate mounted into its container.
Do not change unrelated ENV settings, browser auth, existing proxy routes or
services. Preserve workspaces and credentials when rerunning setup.

Verify from the actual Jarvis runtime network using `scripts/probe.py` before
claiming success. Check authenticated/unauthenticated requests, installed app
versions, and a small real edit with output download. Resolve source files using
Jarvis's existing access rules. Retain originals. Full-size rendering and GPU
selection are app-specific; do not infer GPU use from the presence of a GPU.

Read the README's maintenance and troubleshooting sections for service logs,
version mismatch, CA trust, mode/profile gating and background execution. Stop
the gateway and inspect active jobs before updating apps; retain old releases
and project backups. Use `craft_inspect` to recover job/request IDs, collect
outputs or request cancellation. A lost reply does not authorize repeating an
edit; an interrupted job is not automatically replayed.

When the user points an agent at this file, complete the authorized setup and
verification. Ask only for missing host/access choices that cannot be inferred;
never request passwords or private keys in chat. Report the selected mode,
safe endpoint, supported actions and verified result, with remaining platform
limitations. Do not commit or push unless requested.

For editing, use `craft_image` action `edit` with ordered `edits`, or
`craft_video` action `edit` with source `clips` and `video_edits`. Native
project follow-ups pass the returned `editable_project_ref` as that named tool
input (omitting flattened `sources`), expected
`project_revision`, and the actual layer or clip IDs in `document`. Never
flatten to PNG/MP4 when the user wants to revise existing editable text.
Preserve the source image/footage; a standalone EffectCraft title is not a
substitute for text on supplied media. Verify full caption visibility and
source preservation, not just output-file validity. Timed video captions are
supplied graphic overlays, not generated transcripts. See the README for
exact parameters, limits and example revisions.

Video `update_text` may omit `text` for placement/style changes. Omit timing;
copy timing from the selected `document.overlays` entry, or echo `start: 0`
and `duration: null`. All retain the saved timing; different values are rejected.
Explicit frame
changes on a native revision refit footage and reflow text; omitted dimensions
preserve the saved layout. `assemble` keeps its 640x360 default canvas.

Crop/overlay rectangles use source pixels. Web edit context reports full source
and preview dimensions; never infer source coordinates from the preview size.
Wait for an active project job to finish before a revision; inspect/collect
instead of retrying a busy or uncertain edit.
