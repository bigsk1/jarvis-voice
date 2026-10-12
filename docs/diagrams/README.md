# Jarvis diagrams

These standalone Archify pages describe the repository at the commit recorded
in each source JSON's `meta.repository`. Click source markers to inspect the
supporting code. The pages include search, focus, route highlighting, light/dark
themes and canonical PNG/JPEG/WebP/SVG exports without external viewer libraries.

| Diagram | Interactive page | Editable source | SVG preview |
| --- | --- | --- | --- |
| Runtime architecture | [HTML](jarvis-runtime-architecture.html) | [JSON](jarvis-runtime-architecture.architecture.json) | [SVG](jarvis-voice-runtime.svg) |
| Workflow execution lifecycle | [HTML](jarvis-workflow-execution-lifecycle.html) | [JSON](jarvis-workflow-execution-lifecycle.workflow.json) | [SVG](jarvis-workflow-execution-lifecycle.svg) |
| Email inbox sequence | [HTML](jarvis-email-inbox-sequence.html) | [JSON](jarvis-email-inbox.sequence.json) | [SVG](jarvis-email-inbox-sequence.svg) |
| Email inbox data flow | [HTML](jarvis-email-inbox-dataflow.html) | [JSON](jarvis-email-inbox.dataflow.json) | [SVG](jarvis-email-inbox-dataflow.svg) |

The published runtime and workflow pages are
[runtime architecture](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-runtime-architecture.html)
and [workflow execution lifecycle](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-workflow-execution-lifecycle.html).

## Stable filenames and publishing

`jarvis-voice-runtime.svg` is intentionally named differently from the runtime
HTML and JSON. The project homepage (`index.html`) and README use that preview
filename. Preserve it when exporting a refreshed diagram. The workflow guide
uses `jarvis-workflow-execution-lifecycle.svg`.

Each HTML contains its own SVG; it does not fetch the separate preview file.
A missing preview cannot cause the HTML URL itself to return HTTP 404. For a
404, check the exact path on the published branch, the Pages deployment result
and browser/CDN caching. Both public HTML URLs returned HTTP 200 during the
October 12, 2026 refresh. Local edits become public only after they are committed,
pushed to the Pages source and successfully deployed.

## Refreshing the maintained diagrams

Read the installed Archify skill and trace the current repository before
changing the specifications. Update the pinned commit and source ranges along
with the diagram's facts. From the repository root, using your installed CLI:

```bash
ARCHIFY_BIN=/path/to/archify/bin/archify.mjs
node "$ARCHIFY_BIN" finalize architecture \
  docs/diagrams/jarvis-runtime-architecture.architecture.json \
  docs/diagrams/jarvis-runtime-architecture.html \
  --repo-root . --quality showcase --out-dir /tmp/jarvis-diagram-checks/runtime --json
node "$ARCHIFY_BIN" finalize workflow \
  docs/diagrams/jarvis-workflow-execution-lifecycle.workflow.json \
  docs/diagrams/jarvis-workflow-execution-lifecycle.html \
  --repo-root . --quality showcase --out-dir /tmp/jarvis-diagram-checks/workflow --json
```

Both commands must exit successfully, including the real-browser gate. Set
`ARCHIFY_CHROME` to your Chrome/Chromium executable when automatic detection is
unavailable. Keep browser diagnostics, captures and local delivery receipts out
of Git; `.gitignore` here excludes adjacent machine-specific receipts. Use fresh
evidence directories when the candidate changes after browser evidence exists.

After a successful finalize, export **SVG** through each page's Export menu and
save it using the stable preview filename above. This preserves Archify's
dual-theme canonical export and removes transient viewer selection/highlights.
Commit the JSON, HTML and SVG together so the previews and interactive pages
describe the same graph.
