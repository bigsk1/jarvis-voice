# Canvas PDF Downloads and xAI Public Sharing

Canvas can export a page as JSON, Markdown, or a portable PDF snapshot in dark
or light appearance. Dark is the default; light remains available for printing
or viewers where a white page is preferred. PDF downloads stay on the Jarvis
host. As a separate opt-in action, an authenticated Canvas user can upload the
selected PDF to the xAI Files API and create an expiring public URL.

This uses a PDF because xAI public file URLs support `application/pdf` but do not
support HTML. It is a static snapshot, not a hosted interactive Canvas page.

## What the PDF contains

- Markdown headings, prose, lists, tables, code blocks, and HTTPS links.
- Rich formatting inside table cells is flattened for PDF compatibility. Links
  from those cells are preserved as clickable entries in a `Table links`
  appendix.
- Standalone public Markdown images as embedded, clickable snapshots. If an
  image cannot be downloaded or safely decoded, its HTTPS link is preserved as
  a fallback. Inline images remain links.
- Standalone YouTube links and common source-line forms (for example,
  `Source video: [title](URL)` or a YouTube URL in a source list) as clickable
  thumbnail cards. Repeated references to the same video remain compact links.
  Playback remains on YouTube because embedded web players are not portable
  across PDF viewers. Other public video and audio references remain clickable
  links.
- Local stash images/media and interactive chart blocks as explicit placeholders.
  Stash identifiers and local file paths are not included in the public
  projection.
- Canvas title, tags, and created/updated metadata. The original `source_query`
  is deliberately omitted.

The Download dialog offers separate **PDF — Dark** and **PDF — Light** choices
alongside the existing JSON and Markdown formats. PDF generation itself does
not require xAI or a cloud API key. Direct callers can use `theme=dark` or
`theme=light` on the PDF export URL; an omitted theme defaults to dark.

For newly generated Canvas content, the preferred cross-surface format is a
complete YouTube watch or `youtu.be` URL on its own line. Canvas can recognize
additional forms, but the canonical standalone form keeps the browser player,
PDF thumbnail card, Markdown download, and future parsers aligned.

## Enable xAI public PDFs

Add these settings to the mode file used to start Canvas (`config/cloud.env` or
`config/local.env`):

```dotenv
XAI_API_KEY="your-xai-api-key"
CANVAS_XAI_PDF_SHARE=true
CANVAS_XAI_PDF_SHARE_DEFAULT_TTL_DAYS=7
CANVAS_XAI_PDF_SHARE_MAX_BYTES=8388608
```

Restart Canvas after changing the mode file. The **Publish PDF** button appears
only when the feature flag is true and `XAI_API_KEY` is nonblank. Grok CLI OAuth
chat credentials do not authorize the xAI Files API. Enabling this in local mode
is an explicit cloud-egress choice.

The UI offers 1, 7, or 30 days. Seven days is the default. Jarvis applies the
expiration to the uploaded xAI file, then creates a public URL that inherits that
file lifetime.

## Publish and revoke

1. Open a Canvas page and select **Publish PDF**.
2. Choose dark or light appearance and review that rendered PDF preview plus the
   publish-check findings. Changing the theme clears the confirmation and loads
   a fresh preview.
3. Choose an expiration, acknowledge that the reviewed file will be public, and
   publish.
4. Copy or open the returned `https://files-cdn.x.ai/...` URL.
5. Use **Revoke** in the page's share history to revoke the URL and delete the
   xAI file early.

The local catalog is stored at
`data/canvas/.shares/xai_pdf_registry.json`. It records file/share IDs, hashes,
PDF theme, timestamps, expiration, and lifecycle state. It does not store the
xAI API key or PDF contents. Expired catalog entries remain as history; active
entries can be revoked from the Canvas dialog. Shares created before theme
selection was added are light PDFs and appear as light in the history.

A published PDF is an independent xAI file. Deleting its source Canvas page does
not revoke that public URL; revoke active shares from the page dialog before
deleting the page.

## Safety boundary

Before publishing, Jarvis generates the final PDF, validates its PDF structure
and size, extracts its rendered text, and runs a credential-oriented scan. API
keys, bearer tokens, private keys, and similar secret patterns are hard blocks.
Email addresses and omitted local links are warnings so the user can make the
final judgment from the preview.

Generating a PDF can make outbound HTTPS requests for public image bytes and
YouTube thumbnails. The downloader sends no Canvas cookies, credentials, or API
keys; rejects credential-bearing URLs, nonstandard ports, and private or local
DNS/IP targets on every redirect; accepts only common raster image types; and
enforces item-count, byte, pixel, dimension, redirect, and time limits. Images
are decoded, resized when necessary, and re-encoded without their original
metadata before being embedded. Opening the resulting PDF does not fetch those
images again.

The text credential scanner does not perform OCR on embedded image pixels. The
preview therefore warns whenever public image pixels are included, and the user
must visually inspect them before publishing. Fetching a public image also
reveals the Jarvis host's network address to that image host at export time.

The publish request carries fingerprints of both the page fields and the exact
themed PDF used for that preview. If the title, content, tags, displayed
timestamps, selected theme, or rendered PDF change before the user clicks
Publish, the request stops and requires a fresh preview.

The publish routes are intentionally outside Canvas's unauthenticated internal
`/api/pages` route prefix. When Canvas authentication is enabled, PDF export,
preview, publish, history, and revoke require an authenticated Canvas session.

The scanner is a backstop, not a guarantee that a page contains no personal or
sensitive information. The confirmation step is still required because anyone
with the URL can view the PDF until it expires or is revoked.

## Failure behavior

- A failed xAI public-URL creation or local catalog write triggers best-effort
  revocation and deletion of the newly uploaded file.
- A failed, unsafe, oversized, unsupported, or slow public-media download does
  not fail the PDF export. Jarvis preserves the public HTTPS link and renders an
  explicit preview-unavailable fallback instead.
- Revoke removes public access first, then deletes the xAI file. If deletion
  needs retrying, the catalog records `revoked_cleanup_pending`; the URL has
  already been revoked.
- xAI responses are accepted only when the public URL uses HTTPS and the
  `files-cdn.x.ai` host.

References: [xAI public URLs](https://docs.x.ai/developers/files/public-urls),
[upload](https://docs.x.ai/developers/rest-api-reference/files/upload),
[manage](https://docs.x.ai/developers/rest-api-reference/files/manage), and
[download](https://docs.x.ai/developers/rest-api-reference/files/download).
