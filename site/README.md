# Jarvis Voice website

The GitHub Pages experience is intentionally build-free. The root `index.html`
loads `site/css/site.css`, `site/js/site.js`, existing repository SVGs, and the
optimized screenshots in `site/images/`.

## Preview

From the repository root:

```bash
python3 -m http.server 8080
```

Then open `http://localhost:8080/`. A local server is preferred over opening the
HTML file directly because it matches the relative-path behavior used by GitHub
Pages under `/jarvis-voice/`.

## Assets

No additional assets are required. The eight WebP files are optimized derivatives
of screenshots tracked in `docs/images/`; source files remain the canonical
full-resolution versions.

| Website image in `site/images/` | Source in `docs/images/` |
| --- | --- |
| `jarvis-web.webp` | `jarvis-web-ui.png` |
| `jarvis-canvas.webp` | `jarvis-canvas-ui.png` |
| `jarvis-tui.webp` | `jarvis-tui.png` |
| `memory-browser.webp` | `jarvis-memory-ui.png` |
| `jarvis-images.webp` | `jarvis-image-gallery.png` |
| `jarvis-videos.webp` | `jarvis-video-gallery.png` |
| `jarvis-intelligence.webp` | `jarvis-intelligence-ui.png` |
| `jarvis-logs.webp` | `jarvis-logs-viewer.png` |

The five refreshed Web, Canvas, Memory, Intelligence and Logs images show the
actual frontend with public sample data. Capture them through the
[isolated UI preview](../tests/visual/README.md), rather than opening private
operator data. The existing terminal, image-gallery and video-gallery captures
remain unchanged. Reflection and Scheduled Tasks have separate documentation
screenshots; they do not need additional website variants.

The animated mark is reused directly from
`jarvis-web/client/assets/jarvis-hud-logo.svg`, and both architecture previews
remain linked to their existing interactive HTML pages.

After updating the five source PNGs through the preview, regenerate their
website variants using the maintained exporter and the existing Pillow
dependency:

```bash
.venv/bin/python tests/visual/export_site_images.py
```

This writes only the five refreshed UI WebPs at up to 1600 pixels wide, quality
84; it leaves the terminal and media-gallery files untouched. Use
`--output /tmp/jarvis-site-images` to review exports elsewhere first. The current
UI exports are 1600 × 1000. Keep the image dimensions and descriptions in
`index.html` and `site/js/site.js` aligned when captures change. The showcase
fits the full screenshot into its frame; the thumbnail rail scrolls on small
screens.

## Design system

- Dark obsidian surfaces keep product screenshots and telemetry legible.
- Cyan communicates live system activity; violet marks intelligence and durable
  state; green marks successful deterministic execution.
- The command deck and constellation tell the product story through interaction,
  while real screenshots and architecture diagrams provide evidence.
- Motion respects `prefers-reduced-motion`; navigation, dialogs, tabs, and the
  gallery are keyboard accessible.
