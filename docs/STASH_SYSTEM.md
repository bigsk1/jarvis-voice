# Stash System Design

> **Status**: ✅ Implemented (v2.14)
> **Purpose**: Generic artifact storage layer for the Jarvis ecosystem
> **Updated**: 2026-04-17 - Documented Jarvis Web **stash viewer** (`/stash/view/...`)

---

## 1. Problem Statement

Jarvis currently has several storage layers, but none suited for **intermediate task artifacts**:

| Layer | For Whom | Modality | Lifetime | Limitation |
|-------|----------|----------|----------|------------|
| **Memory DB** | LLM brain | Text/JSON | Medium/long-term | Text only, no files |
| **Canvas** | Human/LLM joint | Markdown | Long-lived | Text only, human-facing |
| **Context** | LLM only | Tokens | Per-conversation | Lost after task |
| `/tmp` | System only | Anything | Ephemeral | Unstructured, lost on reboot |

### Missing Capability

Multi-step workflows like this are currently impossible:

```
Web Search → Download Image → OCR → Summarize → Compose PDF → Print
```

Each tool has no standard way to:
- Save/retrieve files for other tools
- Maintain artifacts across tool calls
- Clean up after tasks complete

---

## 2. What is Stash?

**Stash** is a **generic, structured artifact storage layer** for the entire Jarvis ecosystem.

> **Key Principle**: Stash is **storage-first**. Document composition (`stash.compose`) is
> one consumer of stash, not its core purpose. Any tool that produces or consumes files
> should use stash as the standard artifact layer.

### Characteristics

| Property | Description |
|----------|-------------|
| **Machine-facing** | Not a user UI surface like Canvas |
| **Multimodal** | Images, PDFs, JSON, text, audio, binaries |
| **Addressable** | Tools reference by `space_id` + `file_id` |
| **Scoped** | Organized by "space" (task/run), not one giant folder |
| **Lifecycle-managed** | TTL + scope-based auto-cleanup |
| **Cross-session** | Spaces can persist across conversations |

### Use Cases Beyond Documents

| Use Case | Examples |
|----------|----------|
| **Downloaded media** | Images, audio clips, video thumbnails |
| **Cached model outputs** | Expensive research summaries, API responses |
| **Intermediate data** | CSV for analytics, JSON config snapshots |
| **Audio workflows** | TTS output clips, STT transcriptions |
| **Training artifacts** | Prompt examples, evaluation outputs |
| **Debug artifacts** | Conversation logs, tool call traces |
| **Composed documents** | PDFs, reports (one consumer, not the only one) |

### Directory Structure

```
data/stash/
├── space_20251211_123456_abcd/
│   ├── meta.json              # Space metadata
│   ├── french_bulldog.jpg     # Downloaded image
│   ├── schedule.txt           # Generated text
│   └── schedule.pdf           # Composed document
├── space_20251211_234567_efgh/
│   └── ...
└── .cleanup_marker            # For maintenance scripts
```

### Space Metadata (`meta.json`)

```json
{
  "space_id": "space_20251211_123456_abcd",
  "created_at": "2025-12-11T12:34:56Z",
  "last_used_at": "2025-12-11T12:36:10Z",
  "labels": ["french_bulldog", "exercise_schedule"],
  "owner": "boss",
  "scope": "session",
  "ttl_days": 7,
  "retention_policy": "temporary",
  "pinned": false,
  "files": [
    {
      "file_id": "f_94d9846c5f124f37",
      "name": "french_bulldog.jpg",
      "stored_name": "french_bulldog.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 123456,
      "hash_sha256": "a1b2c3d4...",
      "source": "url",
      "source_url": "https://example.com/dog.jpg",
      "tool_origin": "web_search",
      "tags": ["image", "dog"],
      "created_at": "2025-12-11T12:35:00Z"
    }
  ]
}
```

### Space Scope Types

| Scope | Description | Cleanup Behavior |
|-------|-------------|------------------|
| `session` | Ephemeral, tied to single conversation | Auto-clean at session end + TTL |
| `user` | Cross-session, owned by user | Respect TTL, require explicit cleanup |
| `shared` | (Future) Global templates/resources | Never auto-delete |

### Retention policies

New spaces receive an automatic policy unless the caller supplies `ttl_days`:

| Policy | Default | Examples |
|---|---:|---|
| `temporary` | 7 days | Session workflow intermediates and research scratch data |
| `generated_media` | 30 days | Stash duplicates of generated images, videos, and music |
| `source_artifact` | 120 days | Web/API uploads, PDFs, downloads, and project/user-scoped conversions |
| `explicit` | Caller value | A space created or updated with an explicit `ttl_days` |

Pinned spaces never expire. In addition, scheduled cleanup protects any stash
space still referenced by a saved Web conversation. Legacy spaces carrying the
old default of 7 days are classified before cleanup; legacy custom TTL values
are preserved as `legacy_explicit`.

### File ID vs Filename

**Important**: `file_id` and `name` are separate concepts:

- `file_id`: Internal unique identifier (can be UUID or sanitized name)
- `name`: Human-readable display name
- `stored_name`: Actual filename on disk (sanitized)

For v1, `file_id == stored_name` is acceptable, but the schema supports decoupling later.

### Stash viewer (Jarvis Web UI)

The main chat UI can link to a **read-only viewer** for text and Markdown artifacts stored in stash. It is implemented as a standalone page in the Jarvis Web server (not the in-chat transcript renderer).

| Item | Detail |
|------|--------|
| **URL** | `/stash/view/<space_id>/<file_id>` — `space_id` and `file_id` are URL-encoded path segments matching the stash URI `stash://<space_id>/<file_id>`. |
| **Raw API** | `GET /api/stash/<space_id>/<file_id>` — same artifact; used for download and “raw” open. |
| **Auth** | Uses the same session as the Web UI (`Utils.auth.fetch`); unauthenticated requests fail like other protected API routes. |
| **Markdown** | Content typed as Markdown (or `.md` filename) is rendered with the shared Markdown parser. |
| **Other text** | Plain text, JSON (pretty-printed when valid JSON), CSV, logs, etc. are shown in a monospace-friendly viewer. |
| **Binary / non-text** | The page explains that the file is not text and links to the raw URL instead of rendering bytes. |

Implementation reference: `jarvis-web/server/app.py` (route `serve_stash_viewer`), `jarvis-web/client/stash-viewer.html`.

**Jarvis Canvas** serves the same path pattern on the Canvas port (default `8890`): `jarvis-canvas/server/routes/stash.py` (`stash_viewer_page`) and `jarvis-canvas/client/static/stash-viewer.html`. Canvas page rendering (`jarvis-canvas/client/static/js/canvas.js`) rewrites `stash://` links and `/api/stash/<space>/<file>` references to `/stash/view/...` for reading, while Markdown **images** keep `/api/stash/...` so images and other binaries still load.

Example (Web UI): `http://127.0.0.1:5001/stash/view/space_20260417_001005_3e95a321/f_431faadfb3e9` — on Canvas, use port `8890` with the same path.

---

## 3. Tool API Design

### 3.1 `stash.open_space`

Create or resume a space.

**Input:**
```json
{
  "space_id": "optional - omit to create new",
  "labels": ["optional", "tags"],
  "scope": "session",
  "ttl_days": 7
}
```

**Output:**
```json
{
  "ok": true,
  "space_id": "space_20251211_123456_abcd",
  "speech": "Created new stash space",
  "data": {
    "space_id": "space_20251211_123456_abcd",
    "path": "data/stash/space_20251211_123456_abcd",
    "scope": "session",
    "is_new": true
  }
}
```

**Behavior:**
- If `space_id` provided and exists → resume it
- Else → create new with generated ID
- Updates `last_used_at` on access

---

### 3.2 `stash.info`

Get metadata about a space (without listing all files).

**Input:**
```json
{
  "space_id": "space_20251211_123456_abcd"
}
```

**Output:**
```json
{
  "ok": true,
  "speech": "Space has 3 files, 456KB total",
  "data": {
    "space_id": "space_20251211_123456_abcd",
    "created_at": "2025-12-11T12:34:56Z",
    "last_used_at": "2025-12-11T12:36:10Z",
    "labels": ["french_bulldog"],
    "scope": "session",
    "ttl_days": 7,
    "pinned": false,
    "total_size_bytes": 456789,
    "file_count": 3
  }
}
```

**Use cases:**
- Decide whether to reuse or clean a space
- Quick summaries in logs/monitoring
- LLM choosing between existing spaces

---

### 3.3 `stash.save`

Unified entry point for saving content.

**Input (text):**
```json
{
  "space_id": "optional - uses current session space",
  "name": "schedule.txt",
  "kind": "text",
  "text": "Exercise schedule for French Bulldog...",
  "on_conflict": "error",
  "tags": ["schedule", "generated"]
}
```

**Input (URL download):**
```json
{
  "space_id": "optional",
  "name": "bulldog.jpg",
  "kind": "url",
  "url": "https://example.com/french-bulldog.jpg",
  "on_conflict": "overwrite"
}
```

**Input (JSON):**
```json
{
  "space_id": "optional",
  "name": "data.json",
  "kind": "json",
  "json": { "exercises": ["walk", "fetch", "rest"] }
}
```

**Input (base64 binary):**
```json
{
  "space_id": "optional",
  "name": "image.png",
  "kind": "base64",
  "data": "iVBORw0KGgo..."
}
```

**Output:**
```json
{
  "ok": true,
  "speech": "Saved bulldog.jpg to stash",
  "data": {
    "space_id": "space_20251211_123456_abcd",
    "file_id": "f_94d9846c5f124f37",
    "name": "bulldog.jpg",
    "ref": "stash://space_20251211_123456_abcd/f_94d9846c5f124f37",
    "path": "data/stash/space_.../bulldog.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 123456,
    "hash_sha256": "a1b2c3d4..."
  }
}
```

**Kind options:**
| Kind | Description |
|------|-------------|
| `text` | UTF-8 text file |
| `json` | Pretty-printed JSON |
| `url` | HTTP GET, save binary (with security checks) |
| `base64` | Decode and save raw bytes |

**Conflict policy (`on_conflict`):**
| Policy | Behavior |
|--------|----------|
| `error` | Fail if file with same name exists (default) |
| `overwrite` | Replace content, update metadata |
| `version` | Auto-version (schedule.txt → schedule_2.txt) |

The response always includes the actual `file_id` so the agent knows which file to reference.

---

## 3.5 Standard Reference Format

**URI format** (for logs, LLM-level references, human-readable):
```
stash://space_20251211_123456_abcd/f_94d9846c5f124f37
```

**Structured format** (for tool argument schemas):
```json
{
  "space_id": "space_20251211_123456_abcd",
  "file_id": "f_94d9846c5f124f37"
}
```

**Convention**: All tools that accept stash files should accept either:
- `stash_ref`: URI string
- OR `space_id` + `file_id`: Explicit fields

Example in printer tool:
```json
{
  "action": "print",
  "stash_ref": "stash://space_.../schedule.pdf"
}
// OR
{
  "action": "print",
  "space_id": "space_...",
  "file_id": "schedule.pdf"
}
```

### Field Naming: `ref` vs `stash_ref`

The stash URI appears under two different field names depending on where you're looking. This is by design, not a bug.

**Layer 1 — `stash_helper.py` (`save_binary()` return)**

The core library returns `ref`. From the stash's own perspective, it's just a reference — it doesn't need to say "stash" because it IS the stash.

```python
# lib/stash_helper.py save_binary() returns:
{
    "file_id": "f_abc123",
    "name": "image.jpg",
    "ref": "stash://space_xxx/f_abc123",   # <-- "ref"
    "path": "/data/stash/space_xxx/image.jpg",
    ...
}
```

**Layer 2 — Tool `save_to_stash()` wrappers**

Media generation tools have their own `save_to_stash()` wrapper that renames it to `stash_ref` for clarity in the broader tool result context (where "ref" alone would be ambiguous).

```python
# generate_video.py, generate_image.py, generate_music.py, convert_file.py
# Their save_to_stash() returns:
{
    "saved": True,
    "stash_ref": result.get('ref'),   # <-- renamed to "stash_ref"
    "space_id": space.space_id,
    ...
}
```

**Layer 3 — Tool response `data` field (what lands in conversation)**

| Tool | Where the stash URI lives | Field name |
|------|--------------------------|------------|
| `generate_video` | `data.saved.stash_ref` | `stash_ref` (nested in `saved`) |
| `generate_image` | `data.saved.stash_ref` | `stash_ref` (nested in `saved`) |
| `generate_music` | `data.saved.stash_ref` + `data.stash_ref` | `stash_ref` (both) |
| `convert_file` | `data.stash_ref` | `stash_ref` (top-level) |
| `pdf_create` | `data.ref` | `ref` (top-level, no wrapper) |
| `stash` tool | `data.ref` | `ref` (top-level, no wrapper) |

**Why `pdf_create` and `stash` use `ref`**: These tools call `stash_file.save_binary()` directly and pass through its return dict without a `save_to_stash()` wrapper, so the field keeps the helper's original `ref` name.

**Rule for consuming code**: Always check for both. The follow-up extraction in `chat.py` handles this:
1. Check `data.saved.stash_ref` (nested pattern from media tools)
2. Check `data.stash_ref` (direct, from convert_file/music)
3. Check `data.ref` (direct, from pdf_create/stash tool)

**Do not rename or normalize** — the naming works as-is across all tool paths (FastAPI, web UI, terminal, tools). Changing it would risk regressions in 4+ months of integrated code.

---

### 3.4 `stash.list`

List files in a space.

**Input:**
```json
{
  "space_id": "optional - uses current session space"
}
```

**Output:**
```json
{
  "ok": true,
  "speech": "Stash has 3 files",
  "data": {
    "space_id": "space_20251211_123456_abcd",
    "files": [
      {
        "file_id": "bulldog.jpg",
        "name": "bulldog.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 123456,
        "created_at": "2025-12-11T12:35:30Z"
      },
      {
        "file_id": "schedule.txt",
        "name": "schedule.txt",
        "mime_type": "text/plain",
        "size_bytes": 4321,
        "created_at": "2025-12-11T12:35:45Z"
      }
    ]
  }
}
```

---

### 3.4 `stash.read`

Read file contents or get path for binary files.

**Input:**
```json
{
  "space_id": "optional",
  "file_id": "schedule.txt",
  "mode": "auto"
}
```

**Mode options:**
| Mode | Description |
|------|-------------|
| `auto` | Text for small files, path for binary/large |
| `text` | Force text content (fails for binary) |
| `path` | Return path only |
| `metadata` | Return file info only |

**Output (text file):**
```json
{
  "ok": true,
  "speech": "Read schedule.txt",
  "data": {
    "file_id": "schedule.txt",
    "mime_type": "text/plain",
    "content": "Exercise schedule for French Bulldog...\n",
    "size_bytes": 4321
  }
}
```

**Output (binary file):**
```json
{
  "ok": true,
  "speech": "Retrieved bulldog.jpg path",
  "data": {
    "file_id": "bulldog.jpg",
    "mime_type": "image/jpeg",
    "path": "data/stash/space_.../bulldog.jpg",
    "size_bytes": 123456
  }
}
```

---

### 3.5 `stash.compose`

Combine artifacts into a document (PDF).

**Input:**
```json
{
  "space_id": "optional",
  "files": ["bulldog.jpg", "schedule.txt"],
  "output_name": "french_bulldog_schedule.pdf",
  "template": "simple_poster"
}
```

**Template options:**
| Template | Description |
|----------|-------------|
| `simple_poster` | Image at top, text below |
| `report` | Title, sections, footer |
| `plain_text` | Just combine text files |
| `image_grid` | Multiple images in grid |

**Output:**
```json
{
  "ok": true,
  "speech": "Composed french_bulldog_schedule.pdf",
  "data": {
    "file_id": "french_bulldog_schedule.pdf",
    "mime_type": "application/pdf",
    "path": "data/stash/space_.../french_bulldog_schedule.pdf",
    "size_bytes": 98765
  }
}
```

**Implementation options:**
- `reportlab` (Python native PDF)
- `weasyprint` (HTML→PDF)
- `wkhtmltopdf` (if installed)
- `fpdf2` (simple, lightweight)

---

### 3.7 `stash.update`

Update space metadata (TTL, pinned status, labels).

**Input:**
```json
{
  "space_id": "space_20251211_123456_abcd",
  "ttl_days": 30,
  "pinned": true,
  "labels": ["important", "keep"]
}
```

**Output:**
```json
{
  "ok": true,
  "speech": "Space pinned and TTL updated to 30 days",
  "data": {
    "space_id": "space_20251211_123456_abcd",
    "pinned": true,
    "ttl_days": 30
  }
}
```

**Pinning behavior:**
- `pinned: true` → Space will NOT be auto-deleted by cleanup jobs
- Useful for long-term report libraries, reference materials
- Explicit `stash.cleanup(space_id)` still works on pinned spaces

---

### 3.8 `stash.cleanup`

Delete spaces (single or expired).

**Input (specific space):**
```json
{
  "space_id": "space_20251211_123456_abcd"
}
```

**Input (all expired):**
```json
{
  "mode": "expired_only"
}
```

**Output:**
```json
{
  "ok": true,
  "speech": "Cleaned up 3 expired spaces",
  "data": {
    "deleted_spaces": 3,
    "freed_bytes": 12345678
  }
}
```

**Cleanup strategy (combined):**
1. **Periodic job** (cron/systemd timer):
   - Delete expired where `pinned=false`
   - Enforce global quota (LRU beyond 5GB)
2. **On-demand**:
   - `mode: "expired_only"` for manual maintenance
   - `space_id: "..."` for single space deletion

---

### 3.9 `stash.remember`  (January 2026)

Save a stash artifact to permanent memory with one tool call. Bridges stash (temporary) to memory (permanent).

**Input:**
```json
{
  "action": "remember",
  "search": "google quantum",
  "key": "quantum_computing_article",
  "category": "research",
  "importance": 7,
  "summary": "Optional override summary",
  "summarize": true
}
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `search` | ✅ | Search query to find stash file (matches filename, tags, space labels) |
| `key` | ❌ | Memory key (auto-generated if not provided) |
| `category` | ❌ | Memory category (default: `stash_artifact`) |
| `importance` | ❌ | 1-10 importance score (default: 5) |
| `summary` | ❌ | Override the auto-generated summary |
| `summarize` | ❌ | Use LLM to summarize large content (default: false) |

**Output:**
```json
{
  "ok": true,
  "speech": "Saved 'google_quantum_article.txt' to memory",
  "data": {
    "memory_key": "stash_google_quantum_article_abc123",
    "file_name": "google_quantum_article.txt",
    "space_id": "space_20260119_011530_e688ca88",
    "file_id": "google_quantum_article.txt",
    "content_truncated": false,
    "llm_summarized": true,
    "metadata": {
      "stash_ref": "stash://space_20260119_011530_e688ca88/google_quantum_article.txt",
      "space_id": "space_20260119_011530_e688ca88",
      "file_id": "google_quantum_article.txt",
      "file_name": "google_quantum_article.txt",
      "mime_type": "text/plain",
      "size_bytes": 15432,
      "tags": ["web_extract", "text"],
      "tool_origin": "crawl_url",
      "stash_created_at": "2026-01-19T01:15:30Z",
      "content_truncated": false,
      "llm_summarized": true,
      "is_text": true,
      "hash_sha256": "a1b2c3d4..."
    }
  }
}
```

**Content Handling:**

| File Type | Size | Behavior |
|-----------|------|----------|
| Text/JSON | ≤2KB | Full content stored |
| Text/JSON | >2KB | Truncated to 2KB OR LLM-summarized (if `summarize: true`) |
| PDF | Any | Text extracted via `pdf_read` tool, then summarized/truncated |
| Binary | Any | Metadata only (no content extraction) |

**LLM Summarization:**

When `summarize: true` is set:
1. Content is sent to configured LLM provider
2. LLM extracts key facts for embedding-friendly storage
3. Result is limited to ~300 tokens
4. Works with text, JSON, and PDFs

**PDF Processing:**

PDFs are automatically processed using the `pdf_read` tool:
1. `stash.remember` detects `application/pdf` mime type
2. Internally calls `pdf_read` with `action: extract_text`
3. Extracted text is then summarized/truncated like other text
4. Metadata includes `pdf_extracted: true`

**Search Matching:**

The `search` query is split into terms and matched against:
- Filename (e.g., `google_quantum_article.txt`)
- File tags (e.g., `["web_extract", "quantum"]`)
- Space labels (e.g., `["research", "google"]`)

All terms must match somewhere in the combined text.

**Use Cases:**
```
"Jarvis, save that stash data about google quantum breakthrough"
→ stash.remember(search="google quantum", category="research")

"Remember the bitcoin analysis PDF"
→ stash.remember(search="bitcoin analysis pdf", summarize=true)

"Save the crawled article to memory with high importance"
→ stash.remember(search="crawled article", importance=9)
```

---

## 4. Security Considerations

### 4.1 URL Download Security (Redirect-Aware SSRF Protection)

**Risks:**
- Downloading malware disguised as images
- SSRF (Server-Side Request Forgery) to internal services
- Redirect-based SSRF bypass (benign.com → 127.0.0.1)
- Large file DoS

**Mitigations:**

```python
# In stash.save when kind="url"
import socket
import ipaddress

ALLOWED_SCHEMES = ['http', 'https']
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_REDIRECTS = 3
ALLOWED_MIME_TYPES = [
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf',
    'text/plain', 'text/csv', 'text/html',
    'application/json',
]

# Block private/internal IP ranges
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('127.0.0.0/8'),       # Loopback
    ipaddress.ip_network('10.0.0.0/8'),        # Private
    ipaddress.ip_network('172.16.0.0/12'),     # Private
    ipaddress.ip_network('192.168.0.0/16'),    # Private
    ipaddress.ip_network('169.254.0.0/16'),    # Link-local
    ipaddress.ip_network('::1/128'),           # IPv6 loopback
    ipaddress.ip_network('fe80::/10'),         # IPv6 link-local
    ipaddress.ip_network('fc00::/7'),          # IPv6 private
]

def is_blocked_ip(ip_str: str) -> bool:
    """Check if IP is in blocked ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in BLOCKED_IP_RANGES)
    except ValueError:
        return True  # Invalid IP = blocked

def validate_url_with_dns(url: str) -> bool:
    """Validate URL including DNS resolution to prevent SSRF."""
    parsed = urlparse(url)

    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SecurityError(f"Scheme {parsed.scheme} not allowed")

    # Resolve hostname to IP and check
    hostname = parsed.hostname
    try:
        ip = socket.gethostbyname(hostname)
        if is_blocked_ip(ip):
            raise SecurityError(f"Host {hostname} resolves to blocked IP {ip}")
    except socket.gaierror:
        raise SecurityError(f"Cannot resolve hostname {hostname}")

    return True

def safe_download(url: str, max_size: int = MAX_FILE_SIZE) -> bytes:
    """Download with redirect handling, size limit, and content-type check."""

    # Disable auto-redirects, handle manually
    session = requests.Session()
    response = session.get(url, stream=True, timeout=30, allow_redirects=False)

    redirects = 0
    while response.is_redirect and redirects < MAX_REDIRECTS:
        redirect_url = response.headers.get('Location')
        # Re-validate each redirect URL!
        validate_url_with_dns(redirect_url)
        response = session.get(redirect_url, stream=True, timeout=30, allow_redirects=False)
        redirects += 1

    if response.is_redirect:
        raise SecurityError(f"Too many redirects (>{MAX_REDIRECTS})")

    # Check content-type
    content_type = response.headers.get('Content-Type', '').split(';')[0]
    if content_type not in ALLOWED_MIME_TYPES:
        raise SecurityError(f"Content-Type {content_type} not allowed")

    # Check content-length
    content_length = int(response.headers.get('Content-Length', 0))
    if content_length > max_size:
        raise SecurityError(f"File too large: {content_length} bytes")

    # Stream download with size check
    data = b''
    for chunk in response.iter_content(chunk_size=8192):
        data += chunk
        if len(data) > max_size:
            raise SecurityError(f"File exceeded max size during download")

    return data
```

### 4.2 File Type Validation

**Additional checks:**

```python
import magic  # python-magic library

def validate_file_content(data: bytes, claimed_mime: str) -> bool:
    """Validate actual file content matches claimed type."""
    detected = magic.from_buffer(data, mime=True)

    # If Content-Type was missing/generic, but magic detects unsupported type → reject
    if claimed_mime in ['application/octet-stream', '']:
        if detected not in ALLOWED_MIME_TYPES:
            raise SecurityError(f"Detected unsupported type: {detected}")

    # Allow some flexibility (jpeg vs jpg)
    if detected != claimed_mime:
        safe_mismatches = {
            ('image/jpeg', 'image/jpg'),
            ('text/plain', 'application/octet-stream'),
        }
        if (detected, claimed_mime) not in safe_mismatches:
            raise SecurityError(f"Content mismatch: claimed {claimed_mime}, detected {detected}")

    return True
```

### 4.3 Archive/Decompression Bombs

**For v1: DO NOT allow compressed formats in `ALLOWED_MIME_TYPES`:**
- No `application/zip`
- No `application/x-tar`
- No `application/gzip`

If archive support is needed later, create a separate `unzip` tool with:
- Decompressed size limits
- Nested archive limits
- Explicit user confirmation

### 4.3 Filename Sanitization

```python
import re
import os

def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    # Remove path separators
    name = os.path.basename(name)

    # Remove dangerous characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)

    # Limit length
    name = name[:200]

    # Ensure not empty
    if not name or name in ['.', '..']:
        name = 'unnamed_file'

    return name
```

### 4.4 Disk Space Management

```python
MAX_SPACE_SIZE = 500 * 1024 * 1024  # 500MB per space
MAX_TOTAL_STASH = 5 * 1024 * 1024 * 1024  # 5GB total

def check_space_quota(space_path: str, new_file_size: int) -> bool:
    """Check if adding file would exceed quotas."""
    # Check space size
    space_size = sum(
        os.path.getsize(os.path.join(space_path, f))
        for f in os.listdir(space_path)
        if os.path.isfile(os.path.join(space_path, f))
    )
    if space_size + new_file_size > MAX_SPACE_SIZE:
        raise QuotaError(f"Space quota exceeded")

    # Check total stash size
    stash_dir = os.path.dirname(space_path)
    total_size = sum(
        os.path.getsize(os.path.join(root, f))
        for root, dirs, files in os.walk(stash_dir)
        for f in files
    )
    if total_size + new_file_size > MAX_TOTAL_STASH:
        raise QuotaError(f"Total stash quota exceeded")

    return True
```

---

## 5. Integration Patterns

### 5.1 Core Pattern: "If You Emit External Data, Stash It"

**Guideline for ALL future tools:**

> If a tool downloads data or creates a large artifact → it should:
> 1. Write it into stash (via internal helper or tool call)
> 2. Return `stash_ref` or `{space_id, file_id}` instead of raw bytes

This prevents huge payloads in tool arguments and keeps everything inspectable on disk.

**Tool responsibilities:**

| Tool Type | Responsibility |
|-----------|---------------|
| **Data fetchers** (web_search) | Return URLs only (lightweight) |
| **Materializers** (stash.save) | Turn URLs into stash entries |
| **Processors** (ocr, summarizer) | Read from stash, write to stash |
| **Consumers** (printer, email) | Accept stash references only |

### 5.2 Standard Contract

```python
# web_search returns URLs only
results = web_search("french bulldog images")
# → {"images": [{"url": "https://...", "title": "..."}]}

# Agent materializes URL to stash
stash.save(kind="url", url=results["images"][0]["url"], name="bulldog.jpg")
# → {"file_id": "f_abc123", "ref": "stash://space_.../f_abc123"}

# Downstream tools use stash reference
printer.print(stash_ref="stash://space_.../f_abc123")
```

### 5.3 Tool Updates for Stash Support

| Tool | Change |
|------|--------|
| `printer` | Accept `stash_ref` or `space_id` + `file_id` |
| `canvas` | Add "export to stash" action |
| `send_email` | Accept attachments from stash |
| Future `ocr` | Read from stash, write results to stash |
| Future `transcriber` | Save audio to stash, output text to stash |

### 5.4 Resolver Helper

```python
# In lib/stash_helper.py (shared stash path helper)

def resolve_file_path(args: dict) -> str:
    """Resolve file path from args (direct path or stash reference)."""
    # Option 1: Direct path
    if args.get('file_path'):
        return args['file_path']

    # Option 2: Stash URI
    if args.get('stash_ref'):
        # Parse stash://space_id/file_id
        ref = args['stash_ref']
        if ref.startswith('stash://'):
            parts = ref[8:].split('/', 1)
            space_id, file_id = parts[0], parts[1]
            return f"data/stash/{space_id}/{file_id}"

    # Option 3: Explicit space_id + file_id
    if args.get('space_id') and args.get('file_id'):
        return f"data/stash/{args['space_id']}/{args['file_id']}"

    raise ValueError("Provide file_path, stash_ref, or space_id+file_id")
```

### 5.5 Non-Tool Internal Consumers

Stash is not just a tool API—it's Jarvis's **internal artifact system**.

**Internal use cases:**

| Consumer | Use Case |
|----------|----------|
| **Logs** | Store full conversation logs as JSON for debugging |
| **Evaluation** | Keep transcripts + outputs for analysis |
| **Caching** | Store expensive LLM outputs, attach `stash_ref` to Memory DB |
| **Orchestrator** | Save intermediate results between multi-turn tasks |

**Implementation note:**
> Internal services can write to stash directly using the same directory convention
> and `meta.json` schema. The tool API is a public façade over that.

### 5.6 Memory + Stash Architecture

**Key Insight**: Stash is the **workshop**, Memory is the **index**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STASH + MEMORY ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   TOOLS                    STASH                    MEMORY           │
│ ┌──────────────┐       ┌──────────────┐        ┌──────────────┐     │
│ │generate_image│──────▶│ 📦 Workspace │───────▶│ 🧠 Index     │     │
│ │ pdf_create   │──────▶│  (7-day TTL) │───────▶│ (permanent)  │     │
│ │ printer ◀────│───────│              │        │              │     │
│ │ send_email ◀─│───────│              │        │              │     │
│ └──────────────┘       └──────────────┘        └──────────────┘     │
│                                                                      │
│   Artifacts in stash:       Memory entries:                          │
│   - generated_image.jpg     - stash_image_xxx: "STASH: stash://..."  │
│   - report.pdf              - stash_pdf_xxx: "STASH: stash://..."    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Pattern: Save to Both**

Every tool that creates artifacts should:
1. **Save artifact to stash** (temporary storage, `stash://` reference)
2. **Create memory entry** (permanent index pointing to stash)

```python
# Example from generate_image.py
def save_image(image_data, prompt, space):
    # 1. Save to stash
    stash_ref = save_to_stash(image_data, space)

    # 2. Create memory entry (survives stash TTL)
    memory_key = f"stash_image_{space.space_id}"
    memory_value = f"Generated image: {prompt}. STASH: {stash_ref}. File: {filename}"
    db.remember(key=memory_key, value=memory_value, category="stash_artifact")
```

**Cross-Session Recall**

User asks later: *"Where is that bitcoin image I generated?"*

1. Memory search finds: `"stash_image_xxx: Generated image: bitcoin... STASH: stash://..."`
2. LLM extracts stash reference from memory
3. Tool resolves `stash://` to actual file path

**Graceful Degradation**

Stash has a 7-day TTL, but memory entries persist forever. Handle expired stash:

```python
from stash_helper import safe_resolve_file

# Try stash first, fallback to other known paths
result = safe_resolve_file(
    stash_ref="stash://space_xxx/file_id",
    file_path="/path/to/known/file.jpg",
    fallback_paths=["/home/user/images/"]
)

if result['found']:
    use_file(result['path'])
else:
    # Stash expired, no fallback - inform user
    speech = "That file has expired from the stash."
```

**Tools Using This Pattern**

| Tool | Stash | Memory | Graceful TTL |
|------|-------|--------|--------------|
| `generate_image` | ✅ Saves | ✅ Saves | ✅ |
| `pdf_create` | ✅ Saves | ✅ Saves | ✅ |
| `pdf_read` | ✅ Reads/Writes | N/A | ✅ |
| `stash.remember` | ✅ Reads | ✅ Saves | ✅ |
| `printer` | ✅ Resolves | N/A | ✅ |
| `send_email` | ✅ Resolves | N/A | ✅ |
| `canvas` | N/A | ✅ Already | N/A |

### 5.7 The `stash.remember` Bridge

**Problem**: Stash artifacts are temporary (7-day TTL), but users want to persist important findings.

**Solution**: `stash.remember` action bridges stash → memory in one tool call.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    stash.remember FLOW                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   User: "Save that stash about google quantum"                       │
│                           │                                          │
│                           ▼                                          │
│   ┌──────────────────────────────────────────┐                      │
│   │  1. Search stash for "google quantum"    │                      │
│   │     (filename, tags, labels)             │                      │
│   └──────────────────────────────────────────┘                      │
│                           │                                          │
│                           ▼                                          │
│   ┌──────────────────────────────────────────┐                      │
│   │  2. Detect file type                     │                      │
│   │     - text/plain → read content          │                      │
│   │     - application/pdf → call pdf_read    │                      │
│   │     - binary → metadata only             │                      │
│   └──────────────────────────────────────────┘                      │
│                           │                                          │
│                           ▼                                          │
│   ┌──────────────────────────────────────────┐                      │
│   │  3. Process content                      │                      │
│   │     - If >2KB: truncate OR summarize     │                      │
│   │     - If summarize=true: call LLM        │                      │
│   └──────────────────────────────────────────┘                      │
│                           │                                          │
│                           ▼                                          │
│   ┌──────────────────────────────────────────┐                      │
│   │  4. Save to Memory DB                    │                      │
│   │     - key: stash_{filename}_{hash}       │                      │
│   │     - value: content/summary             │                      │
│   │     - metadata: stash_ref, tags, etc.    │                      │
│   └──────────────────────────────────────────┘                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Structured Metadata Storage**

Unlike simple text values, `stash.remember` stores rich metadata:

```json
{
  "key": "stash_google_quantum_abc123",
  "value": "Key facts: Google achieved quantum supremacy...",
  "category": "research",
  "importance": 7,
  "metadata": {
    "stash_ref": "stash://space_xxx/google_quantum.txt",
    "space_id": "space_xxx",
    "file_id": "google_quantum.txt",
    "file_name": "google_quantum.txt",
    "mime_type": "text/plain",
    "size_bytes": 15432,
    "tags": ["web_extract", "quantum"],
    "tool_origin": "crawl_url",
    "stash_created_at": "2026-01-19T01:15:30Z",
    "content_truncated": false,
    "llm_summarized": true,
    "pdf_extracted": false,
    "is_text": true,
    "hash_sha256": "a1b2c3d4..."
  }
}
```

This metadata enables:
- **Future retrieval**: Find by tool_origin, tags, or stash_ref
- **Graceful degradation**: If stash expires, memory still has content
- **Auditing**: Track which tools created which artifacts

### 5.8 Inter-Tool Calling Pattern

Some tools need to call other tools internally. This is done via subprocess.

**Example: `stash.remember` calling `pdf_read`**

```python
import subprocess
import json
import os

SKILLS_DIR = os.path.dirname(__file__)
AUTO_TOOLS_DIR = os.path.join(SKILLS_DIR, 'auto-tools')

def find_tool(tool_name: str) -> str:
    """Find tool path - check skills/ then skills/auto-tools/"""
    for base_dir in [SKILLS_DIR, AUTO_TOOLS_DIR]:
        tool_path = os.path.join(base_dir, f"{tool_name}.py")
        if os.path.exists(tool_path):
            return os.path.abspath(tool_path)
    return None

def call_tool(tool_name: str, args: dict = None, timeout: int = 60) -> dict:
    """Call another Jarvis tool and return its result."""
    tool_path = find_tool(tool_name)
    if not tool_path:
        return {"ok": False, "error": f"Tool {tool_name} not found"}

    project_root = os.path.join(os.path.dirname(__file__), '..')
    input_data = json.dumps(args or {})

    result = subprocess.run(
        ["python3", tool_path, input_data],
        capture_output=True, text=True,
        timeout=timeout, cwd=project_root
    )

    if result.returncode == 0 and result.stdout:
        return json.loads(result.stdout)
    return {"ok": False, "error": result.stderr}

# Usage in stash.remember for PDF extraction
def extract_pdf_text(file_path: str) -> str:
    result = call_tool('pdf_read', {
        'action': 'extract_text',
        'file_path': file_path
    })
    if result.get('ok'):
        return result.get('data', {}).get('text', '')
    return None
```

**Key Points:**
1. **Search both directories**: `skills/` and `skills/auto-tools/`
2. **Run from project root**: Ensures `lib/` imports work
3. **JSON in/out**: Pass args as `sys.argv[1]`, parse stdout as JSON
4. **Handle timeouts**: Set appropriate timeout per tool type

See also: [TOOL_CALLING_SYSTEM.md](TOOL_CALLING_SYSTEM.md) for full pattern documentation.

---

## 6. Example Workflow: French Bulldog Exercise Schedule

**User:** "Find a French bulldog image and create a printable exercise schedule"

**Agent flow:**

```
1. stash.open_space(labels=["french_bulldog", "exercise"])
   → space_id: "space_20251211_abc"

2. web_search("french bulldog tricolor black nails")
   → image_url: "https://..."

3. stash.save(space_id, kind="url", url=image_url, name="bulldog.jpg")
   → file_id: "bulldog.jpg"

4. [Agent generates schedule text]

5. stash.save(space_id, kind="text", name="schedule.txt", text="...")
   → file_id: "schedule.txt"

6. stash.compose(space_id, files=["bulldog.jpg", "schedule.txt"],
                 output="schedule.pdf", template="simple_poster")
   → file_id: "schedule.pdf"

7. printer.print(space_id, file_id="schedule.pdf")
   → "Sent to printer"

8. [Optional] memory.remember(key="bulldog_schedule_space", value=space_id)
   → For future reference
```

---

## 7. Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create `data/stash/` directory structure
- [ ] Implement `stash.py` tool with open_space, save (text only), list, read
- [ ] Add security validation for filenames
- [ ] Create `stash.tool.json`

### Phase 2: URL Downloads
- [ ] Add `kind="url"` support to stash.save
- [ ] Implement URL validation (no SSRF)
- [ ] Add content-type validation
- [ ] Add file size limits
- [ ] Add `python-magic` for content verification (optional)

### Phase 3: Document Composition
- [ ] Add `stash.compose` action
- [ ] Install PDF library (fpdf2 or reportlab)
- [ ] Create basic templates (simple_poster, report)
- [ ] Support image + text composition

### Phase 4: Tool Integration
- [ ] Update `printer` to accept stash references
- [ ] Update `send_email` for stash attachments
- [ ] Add cleanup cron job or systemd timer

### Phase 5: Polish
- [ ] Add session-implicit space tracking
- [ ] Add Memory DB integration for cross-session ( local and cloud and way to safely sync , use with existing sync scripts that start up on services and or api? or manually?
- [ ] Add quota management UI/commands
- [ ] Documentation and examples

---

## 8. Configuration

**Add to `config/cloud.env` and `config/local.env`:**

```bash
# Stash System
STASH_DIR="data/stash"
STASH_DEFAULT_TTL_DAYS=7
STASH_GENERATED_MEDIA_TTL_DAYS=30
STASH_SOURCE_ARTIFACT_TTL_DAYS=120
STASH_CLEANUP_MAX_SPACES=100
STASH_CLEANUP_MAX_BYTES_MB=512
STASH_MAX_SPACE_SIZE_MB=500
STASH_MAX_TOTAL_SIZE_GB=5
STASH_ALLOWED_DOWNLOAD_HOSTS=""  # Empty = allow all external
STASH_BLOCKED_DOWNLOAD_HOSTS="localhost,127.0.0.1,169.254.169.254"

# Stash LLM Summarization (for stash.remember)
# Optional: Override provider/model for stash.remember summarize=true only.
# Provider falls back to LLM_PROVIDER; model falls back to that provider's default.
# STASH_SUMMARIZE_LLM_PROVIDER="xai"
# STASH_SUMMARIZE_MODEL="gpt-4o-mini"        # OpenAI
# STASH_SUMMARIZE_MODEL="claude-3-5-haiku-latest"  # Anthropic
# STASH_SUMMARIZE_MODEL="qwen3.5:latest"          # Ollama (local)
# STASH_SUMMARIZE_MODEL="grok-4.3"                # xAI API key
# Under xAI OAuth, unsupported API model pins resolve to XAI_OAUTH_MODEL (grok-build)
```

### LLM Summarization Details

When `stash.remember` is called with `summarize: true`:

1. **Provider Detection**: `STASH_SUMMARIZE_LLM_PROVIDER` → `LLM_PROVIDER`
2. **Model Selection**: `STASH_SUMMARIZE_MODEL` → provider default; xAI OAuth resolves through `XAI_OAUTH_MODEL`
3. **Provider Stack**: Uses `create_configured_provider()`—the same mode-aware auth/routing stack as workflows and `text_summarizer`
4. **Server-Side Tools**: Disabled for this plain-text summarization call
5. **Token Limit**: Input truncated to 8000 characters, output limited to 400 tokens
6. **Output Hygiene**: Provider confidence/control annotations are not stored in Memory
7. **Cost**: Separate from orchestrator tool call limits

**Supported Providers:**

| Provider path | Model resolution | Authentication/routing |
|---------------|------------------|------------------------|
| OpenAI | `STASH_SUMMARIZE_MODEL` or `OPENAI_MODEL` | `OPENAI_API_KEY` |
| Anthropic | `STASH_SUMMARIZE_MODEL` or `ANTHROPIC_MODEL` | `ANTHROPIC_API_KEY` |
| Ollama local | `STASH_SUMMARIZE_MODEL` or `OLLAMA_MODEL` | Local daemon |
| Ollama Cloud | `STASH_SUMMARIZE_MODEL` or `OLLAMA_CLOUD_MODEL` | Signed-in daemon or `OLLAMA_API_KEY` direct API |
| xAI API | `STASH_SUMMARIZE_MODEL` or `XAI_MODEL` | `XAI_API_KEY` |
| xAI OAuth | `XAI_OAUTH_MODEL` (`grok-build` by default) | Grok CLI OAuth chat proxy |

**Note**: Summarization calls are independent of the main conversation context.
This means costs are separate from your orchestrator tool call budget.

---

## 9. Design Decisions (Resolved)

| Question | Decision |
|----------|----------|
| **Reference format** | URI (`stash://space/file`) for humans, `{space_id, file_id}` for tools |
| **File ID vs name** | Separate concepts; `file_id` is internal, `name` is display |
| **Conflict handling** | `on_conflict` param: error (default), overwrite, version |
| **Space scoping** | `scope`: session (auto-cleanup), user (persistent), shared (future) |
| **Pinning** | `pinned: true` prevents auto-delete; explicit cleanup still works |
| **Cleanup strategy** | Combined: cron for expired + on-demand for manual |
| **SSRF protection** | IP-based blocking + redirect validation (not just hostname) |
| **Archives** | Not allowed in v1; separate `unzip` tool if needed later |

## 10. Remaining Open Questions

1. **Session tracking**: How does orchestrator track "current" space for a session?
   - Option A: Store in conversation state (cleanest)
   - Option B: Return space_id in every response, LLM remembers
   - Option C: Global "active space" variable per session

2. **Virus scanning**: Worth integrating ClamAV for downloaded files?
   - Adds complexity and dependencies
   - May be overkill for personal assistant
   - Could be optional/configurable (default off)

---

## 11. Stash FastAPI  (Jan 2026)

Read-only API for external integrations, scripts, and programmatic access at **port 8880**.

### Endpoints

```bash
# Statistics
curl http://localhost:8880/api/stash/stats
# → {total_spaces, total_files, total_size_human, by_label, by_tool}

# List spaces with filters
curl "http://localhost:8880/api/stash?limit=20&label=generated_images"
curl "http://localhost:8880/api/stash?tool=generate_image"
curl "http://localhost:8880/api/stash?pinned=true"

# Search spaces
curl "http://localhost:8880/api/stash/search?q=bitcoin"

# Get recent spaces
curl "http://localhost:8880/api/stash/recent?limit=5"

# List all labels with counts
curl http://localhost:8880/api/stash/labels

# Get specific space with files
curl http://localhost:8880/api/stash/space/space_20260118_005400_7374e32c

# Get file info
curl http://localhost:8880/api/stash/space/{space_id}/file/{file_id}

# Download file
curl -O http://localhost:8880/api/stash/space/{space_id}/file/{file_id}/download
```

### Response Examples

**Stats:**
```json
{
  "total_spaces": 149,
  "total_files": 143,
  "total_size_human": "164.5 MB",
  "by_label": {"generated_images": 54, "pdf": 10},
  "by_tool": {"generate_image": 54, "stash": 42}
}
```

**Space with files:**
```json
{
  "space_id": "space_20260118_005400_7374e32c",
  "labels": ["generated_images"],
  "files": [{
    "file_id": "f_5d190ce797c6",
    "name": "generated_bitcoin_infographic.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 2314172,
    "tool_origin": "generate_image"
  }]
}
```

### Use Cases

- **n8n workflows**: Access stash files for automation
- **Backup scripts**: List and download generated images
- **Monitoring**: Track storage usage over time
- **Debugging**: Inspect stash contents via API

### Note: Stash Tool vs FastAPI

| Component | Port | Purpose |
|-----------|------|---------|
| `stash` tool (skills/stash.py) | N/A | Create, manage, download artifacts |
| Stash FastAPI (api/routes/stash.py) | 8880 | Read-only external access |

The `stash` tool has direct DB/file access. The FastAPI is for external integrations only.

See: `docs/api/STASH.md` for full API documentation.

---

## 12. Related Docs

- [Memory System](MEMORY_SYSTEM.md) - Long-term fact storage
- [Canvas System](CANVAS_SYSTEM.md) - Human-facing research notes
- [Tool Calling System](TOOL_CALLING_SYSTEM.md) - Inter-tool calling patterns ⭐ ENHANCED
- [Stash API](api/STASH.md) - FastAPI documentation
- [Canvas API](api/CANVAS.md) - FastAPI documentation
- **PDF Read Tool** (`skills/pdf_read.py`) - PDF extraction, used by `stash.remember`

---

*Last updated: 2026-02-09*
