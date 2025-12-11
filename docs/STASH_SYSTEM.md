# Stash System Design

> **Status**: Design Phase  
> **Purpose**: Structured file store for multi-step task artifacts  
> **Author**: Design discussion 2025-12-11

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

**Stash** is a structured, tool-accessible file store for intermediate artifacts.

### Characteristics

| Property | Description |
|----------|-------------|
| **Machine-facing** | Not a user UI surface like Canvas |
| **Multimodal** | Images, PDFs, JSON, text, binaries |
| **Addressable** | Tools reference by `space_id` + `file_id` |
| **Scoped** | Organized by "space" (task/run), not one giant folder |
| **Lifecycle-managed** | TTL-based auto-cleanup |
| **Cross-session** | Spaces can persist across conversations |

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
  "ttl_days": 7,
  "files": [
    {
      "file_id": "french_bulldog.jpg",
      "name": "french_bulldog.jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 123456,
      "source": "url",
      "source_url": "https://example.com/dog.jpg",
      "created_at": "2025-12-11T12:35:00Z"
    }
  ]
}
```

---

## 3. Tool API Design

### 3.1 `stash.open_space`

Create or resume a space.

**Input:**
```json
{
  "space_id": "optional - omit to create new",
  "labels": ["optional", "tags"],
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
    "is_new": true
  }
}
```

**Behavior:**
- If `space_id` provided and exists → resume it
- Else → create new with generated ID
- Updates `last_used_at` on access

---

### 3.2 `stash.save`

Unified entry point for saving content.

**Input (text):**
```json
{
  "space_id": "optional - uses current session space",
  "name": "schedule.txt",
  "kind": "text",
  "text": "Exercise schedule for French Bulldog..."
}
```

**Input (URL download):**
```json
{
  "space_id": "optional",
  "name": "bulldog.jpg",
  "kind": "url",
  "url": "https://example.com/french-bulldog.jpg"
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
    "file_id": "bulldog.jpg",
    "path": "data/stash/space_.../bulldog.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 123456
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

---

### 3.3 `stash.list`

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

### 3.6 `stash.cleanup`

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

---

## 4. Security Considerations

### 4.1 URL Download Security

**Risks:**
- Downloading malware disguised as images
- SSRF (Server-Side Request Forgery) to internal services
- Large file DoS

**Mitigations:**

```python
# In stash.save when kind="url"

ALLOWED_SCHEMES = ['http', 'https']
BLOCKED_HOSTS = ['localhost', '127.0.0.1', '169.254.169.254', '10.', '192.168.', '172.16.']
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = [
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf',
    'text/plain', 'text/csv', 'text/html',
    'application/json',
]

def validate_url(url: str) -> bool:
    """Validate URL before downloading."""
    parsed = urlparse(url)
    
    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SecurityError(f"Scheme {parsed.scheme} not allowed")
    
    # Check for internal hosts
    host = parsed.hostname.lower()
    for blocked in BLOCKED_HOSTS:
        if host.startswith(blocked) or host == blocked:
            raise SecurityError(f"Host {host} is blocked")
    
    return True

def safe_download(url: str, max_size: int = MAX_FILE_SIZE) -> bytes:
    """Download with size limit and content-type check."""
    response = requests.get(url, stream=True, timeout=30)
    
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

def validate_file_content(data: bytes, expected_mime: str) -> bool:
    """Validate actual file content matches claimed type."""
    detected = magic.from_buffer(data, mime=True)
    
    # Allow some flexibility (jpeg vs jpg)
    if detected != expected_mime:
        # Check if it's a known safe mismatch
        safe_mismatches = {
            ('image/jpeg', 'image/jpg'),
            ('text/plain', 'application/octet-stream'),
        }
        if (detected, expected_mime) not in safe_mismatches:
            raise SecurityError(f"Content mismatch: claimed {expected_mime}, detected {detected}")
    
    return True
```

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

## 5. Integration with Existing Tools

### 5.1 How Tools Use Stash

**Standard contract:**
> When a tool returns a URL or large content, persist it via `stash.save` and pass `file_id` to downstream tools.

**Example flow:**

```python
# web_search returns URLs only
results = web_search("french bulldog images")
# → {"images": [{"url": "https://...", "title": "..."}]}

# Agent saves to stash
stash.save(kind="url", url=results["images"][0]["url"], name="bulldog.jpg")
# → {"file_id": "bulldog.jpg", "space_id": "space_..."}

# Printer uses file_id
printer.print(space_id="space_...", file_id="bulldog.jpg")
```

### 5.2 Tool Updates Needed

| Tool | Change |
|------|--------|
| `printer` | Accept `space_id` + `file_id` as alternative to `file_path` |
| `canvas` | Add "save to stash" action for canvas content |
| `send_email` | Accept attachments from stash |
| Future `ocr` | Read from stash, write results to stash |

### 5.3 Printer Integration Example

```python
# In printer.py

def resolve_file_path(args: dict) -> str:
    """Resolve file path from args (direct path or stash reference)."""
    if args.get('file_path'):
        return args['file_path']
    
    if args.get('space_id') and args.get('file_id'):
        # Load from stash
        space_path = f"data/stash/{args['space_id']}"
        file_path = os.path.join(space_path, args['file_id'])
        if os.path.exists(file_path):
            return file_path
        raise FileNotFoundError(f"File {args['file_id']} not found in stash")
    
    raise ValueError("Either file_path or space_id+file_id required")
```

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
- [ ] Add Memory DB integration for cross-session
- [ ] Add quota management UI/commands
- [ ] Documentation and examples

---

## 8. Configuration

**Add to `config/cloud.env` and `config/local.env`:**

```bash
# Stash System
STASH_DIR="data/stash"
STASH_DEFAULT_TTL_DAYS=7
STASH_MAX_SPACE_SIZE_MB=500
STASH_MAX_TOTAL_SIZE_GB=5
STASH_ALLOWED_DOWNLOAD_HOSTS=""  # Empty = allow all external
STASH_BLOCKED_DOWNLOAD_HOSTS="localhost,127.0.0.1,169.254.169.254"
```

---

## 9. Open Questions

1. **Session tracking**: How does the orchestrator track the "current" space for a session?
   - Option A: Store in conversation state
   - Option B: Return space_id in every response, LLM remembers
   - Option C: Global "active space" variable

2. **Automatic cleanup**: Cron job vs on-demand?
   - Cron is simpler but requires setup
   - On-demand cleanup at session end is more predictable

3. **Virus scanning**: Worth integrating ClamAV for downloaded files?
   - Adds complexity and dependencies
   - May be overkill for personal assistant
   - Could be optional/configurable

4. **Cross-tool references**: Standard format for file references?
   - `stash://space_id/file_id`
   - `{"space_id": "...", "file_id": "..."}`
   - Just pass paths after resolution

---

## 10. Related Docs

- [Memory System](MEMORY_SYSTEM.md) - Long-term fact storage
- [Canvas System](CANVAS_SYSTEM.md) - Human-facing research notes  
- [Tool Development](../AGENTS.md) - Tool creation guidelines

---

*Last updated: 2025-12-11*

