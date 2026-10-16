# UI preview and documentation screenshots

Inspect the real Web, Canvas, Memory, Intelligence and Logs Viewer frontends
without opening an operator's conversations, databases, logs or credentials.
The preview serves the shipped HTML/templates, JavaScript, fonts and CSS with
small, public sample API responses. It imports no production application or
configuration loader and never proxies to a live service.

## Open the preview

From the checkout root, using the normal development environment:

```bash
.venv/bin/python tests/visual/preview.py
```

| UI | Preview |
| --- | --- |
| Web chat | <http://127.0.0.1:8761/> |
| Canvas | <http://127.0.0.1:8764/?page=page_demo_workspace> |
| Memory | <http://127.0.0.1:8762/?mode=cloud#memories> |
| Scheduled tasks | <http://127.0.0.1:8762/?mode=cloud#scheduled> |
| Intelligence | <http://127.0.0.1:8763/?mode=cloud> |
| Logs Viewer | <http://127.0.0.1:8761/logs> |

Stop with **Ctrl+C**. These ports are separate from the normal Jarvis services,
bind only to loopback, and do not change live authentication. Use the numeric
`127.0.0.1` hostname so the sample navigation URLs stay together.

The Web chat opens a sample conversation using a preview-only Socket.IO
stand-in that cannot execute a request. It uses the normal conversation loader
and message/tool renderers.

Select **Insights** or **Reflection** to inspect those Intelligence layouts.
The fixture files include list/detail examples for the other dashboard tabs.
Controls that would save, delete, process, upload or call a model receive a
read-only error or an inert transport response. API filtering and mutations
are not simulated; this preview checks rendering, not backend correctness.
Normal regression tests and authorized live checks remain separate.

## Capture screenshots

Keep the preview running in one terminal. The optional Node capture helper
uses Playwright and Chromium in another; these are developer tools and add no
runtime or normal-install dependencies. Reuse an installed Playwright package
with `--playwright-module`, or prepare temporary browser tooling:

```bash
npm install --prefix /tmp/jarvis-ui-browser --no-save --package-lock=false playwright
/tmp/jarvis-ui-browser/node_modules/.bin/playwright install chromium
node tests/visual/capture.cjs \
  --playwright-module /tmp/jarvis-ui-browser/node_modules/playwright
```

If a host lacks color emoji fonts, supply an existing emoji font file with
`--emoji-font /path/to/NotoColorEmoji.ttf`. The capture helper supplies it only
to the preview browser as a glyph fallback. It installs nothing on the host;
it changes no production stylesheet. The [Noto Emoji project](https://github.com/googlefonts/noto-emoji)
provides the open-source font used for the initial headless captures.

Captures use a 1600 × 1000 CSS-pixel viewport, 1.5 device scale, dark mode,
self-hosted UI fonts, a fixed sample clock and the America/Los_Angeles timezone.
The browser blocks requests outside the four preview origins. No provider,
model, external page, or real application endpoint is contacted.

The helper overwrites these seven named PNGs in `docs/images`, leaving older
screenshots intact. Pass `--output /tmp/jarvis-ui-candidates` to review elsewhere.

After approving new captures, refresh the five matching optimized website
images without changing the existing TUI, image-gallery or video-gallery shots:

```bash
.venv/bin/python tests/visual/export_site_images.py
```

This uses the project's existing Pillow dependency and exports WebP at up to
1600 pixels wide. Full-resolution documentation PNGs remain unchanged.

| Screenshot | View |
| --- | --- |
| `jarvis-web-ui.png` | Sample conversation, tool cards and Markdown answer |
| `jarvis-canvas-ui.png` | Research page and folder tree |
| `jarvis-memory-ui.png` | Saved sample memories and categories |
| `jarvis-intelligence-ui.png` | Learned insights and confidence |
| `jarvis-logs-viewer.png` | Log folders, files and formatted records |
| `jarvis-reflection-queue.png` | Reflection review and batch controls |
| `jarvis-scheduled-tasks.png` | Workflow schedules and recent results |

These are screenshots of the real frontend code with demonstration content.
They are not proof of a live tool execution or model result. Keep fixtures
neutral and free of operator details when adding future examples. Update
fixtures when client response contracts change; missing sample routes return
404 so integration drift remains visible during capture.
