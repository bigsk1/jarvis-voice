# Web UI fonts and offline static assets

Jarvis web UIs are intended to run **without loading JavaScript or fonts from a CDN**. After a normal `git clone` on Linux (Ubuntu is the primary environment), **no extra font install step** is required: the repo contains the `woff2` files and vendored scripts.

## What is self-hosted

### Fonts (`jarvis-web/client/fonts/`)

Only **Inter** and **JetBrains Mono** are used, via `@font-face` in:

- `jarvis-web/client/css/fonts.css` — paths `/fonts/*.woff2` (main web UI on port 5001)
- `jarvis-canvas/client/static/css/fonts.css` — paths `/static/fonts/*.woff2` (Canvas uses the same faces)

**Files kept in git** (eight `woff2` files):

| File | Role |
|------|------|
| `InterVariable.woff2` | Inter, normal, variable weight |
| `Inter-Italic.woff2` | Inter, italic |
| `JetBrainsMono-{Regular,Medium,SemiBold,Bold}.woff2` | Mono UI / code |
| `JetBrainsMono-{Italic,BoldItalic}.woff2` | Mono italic variants |


### JavaScript vendor bundles

- **`jarvis-web/client/vendor/`** — `marked`, `socket.io` (see `vendor/README.md` there).
- **`jarvis-canvas/client/static/vendor/`** — `marked`, DOMPurify, highlight.js (see that folder’s README).

Scripts load **local files first**; some pages include a **CDN `onerror` fallback** only if the local file fails to load (e.g. incomplete deploy). Day-to-day offline use does not hit the CDN.

### Google Fonts and other CDNs

Removed from the UI layer:

- Google Fonts CSS (`fonts.googleapis.com`) — replaced by local `@font-face`.
- Canvas previously used Space Grotesk from Google — aligned with **Inter** + JetBrains Mono locally.

Remaining `https://` references in HTML are usually **optional fallbacks**, in-app links (e.g. GitHub), or embedding YouTube — not required for the shell UI to function offline.

## Sharing fonts across apps (symlinks)

**Jarvis Memory** (`:5002`), **Jarvis Intelligence** (`:5003`), and **Jarvis Canvas** do **not** duplicate the `woff2` tree. They use **symlinks** into `jarvis-web/client/fonts`:

- `jarvis-memory/client/fonts` → `../../jarvis-web/client/fonts`
- `jarvis-intelligence/client/fonts` → `../../jarvis-web/client/fonts`
- `jarvis-canvas/client/static/fonts` → `../../../jarvis-web/client/fonts`

On **Linux/macOS**, Git stores these as symlinks; a fresh clone keeps the layout, so **nothing to run after clone** beyond starting each service as you already do.

### Windows (not the primary target)

If you ever clone on Windows, symlinks need **Developer Mode** or `git config core.symlinks true`, or you must replace symlinks with a real copy of `jarvis-web/client/fonts`. Ubuntu-only deployments can ignore this.

## Install scripts

`install.sh` and similar **do not** need font or vendor steps: assets live in the repo. To **refresh** vendor JS to pinned versions (when online), use:

```bash
./bin/vendor-web-ui-assets.sh
```

That script does **not** download fonts—only third-party JS/CSS bundles listed in the script.

## Tests

`tests/test_web_fonts.py` checks that:

- `fonts.css` references files that exist on disk.
- The main web UI, Memory browser, and Canvas serve font and vendor URLs correctly (including symlinked paths).

## Adding or changing fonts (Nerd Font, mixing families, etc.)

All symlinked UIs read files from **`jarvis-web/client/fonts/`** — that is the **single place** to drop new `woff2` (or `woff`) files.

1. **Add the font files** under `jarvis-web/client/fonts/` (prefer **woff2** for web).
2. **Declare them** in `jarvis-web/client/css/fonts.css` with `@font-face` (`font-family`, `font-weight`, `src: url('/fonts/YourFont.woff2')`).
3. **Point CSS variables** at the new family where you want it, e.g. in `jarvis-web/client/css/variables.css`:
   - `--font-sans` for UI text
   - `--font-mono` for code / monospace
4. **Canvas** uses a separate copy of the same rules in `jarvis-canvas/client/static/css/fonts.css` with paths **`/static/fonts/...`** — add matching `@font-face` blocks there (or keep Canvas on Inter/JetBrains and only change the main web UI).
5. **Memory / Intelligence** use the same `css/fonts.css` as jarvis-web when you **copy** `fonts.css` from jarvis-web after edits (or symlink that file if you prefer one source of truth).

Symlinks only share the **binary files**; the **CSS** that references them is still edited per app when paths differ (`/fonts/` vs `/static/fonts/`).

## Summary

| Concern | Status |
|--------|--------|
| Fonts offline | Yes — local `woff2` + `fonts.css` |
| Main JS offline | Yes — vendored under `vendor/` / `static/vendor/` |
| New clone setup | **No extra font copy** on Ubuntu when symlinks are preserved |
| CDN required for UI | **No** for normal operation |
