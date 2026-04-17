# Vendored browser assets (offline-capable UI)

These files are served from `/vendor/` so the web UI works without internet after a normal install.

| File | Version | Fallback CDN (on load error) |
|------|---------|------------------------------|
| `marked.min.js` | 15.0.6 | jsdelivr `marked@15.0.6` |
| `socket.io.min.js` | 4.7.2 | cdn.socket.io `4.7.2` |

`index.html` uses `onerror` on each `<script>` to retry the CDN if `/vendor/*` is missing (e.g. partial deploy).

Refresh vendored copies (requires network):

```bash
./bin/vendor-web-ui-assets.sh
```

Fonts: self-hosted `woff2` under `/fonts/` with `@font-face` in `css/fonts.css` (linked before `variables.css`). **Memory / Intelligence / Canvas** symlink to `jarvis-web/client/fonts`—see `fonts/README.md`.
