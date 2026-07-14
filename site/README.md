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

No additional assets are required. The six WebP files are optimized derivatives
of real screenshots already tracked in `docs/images/`; source files remain the
canonical full-resolution versions. Current sources: `jarvis-web.jpg`,
`jarvis-canvas` / TUI / video screenshots, `jarvis-image-gallery.png`, and
`memory-browser.jpg`.
The animated mark is reused directly from
`jarvis-web/client/assets/jarvis-hud-logo.svg`, and both architecture previews
remain linked to their existing interactive HTML pages.

To refresh a screenshot, export a 16:9 or wider PNG into `docs/images/`, then
create a WebP no wider than 1600 pixels at roughly 80-84 quality and update the
matching gallery entry in `site/js/site.js`.

## Design system

- Dark obsidian surfaces keep product screenshots and telemetry legible.
- Cyan communicates live system activity; violet marks intelligence and durable
  state; green marks successful deterministic execution.
- The command deck and constellation tell the product story through interaction,
  while real screenshots and architecture diagrams provide evidence.
- Motion respects `prefers-reduced-motion`; navigation, dialogs, tabs, and the
  gallery are keyboard accessible.
