# Jarvis API - Documentation

> **Verified against Jarvis**: v2.53.0 | **Updated**: June 2026

Comprehensive REST API for Jarvis Voice Assistant - includes proactive webhooks, memory management, query interface, and system monitoring.

![reactive-vs-proactive-info-graph](../images/reactive-vs-proactive-info-graph.jpeg)

---

## 📚 Documentation Index

### Getting Started
- **[API Overview](API_OVERVIEW.md)** - Complete endpoint reference, quick start
- **[Ready to Use Guide](READY_TO_USE.md)** - Setup and deployment
- **[API Quick Start](API_QUICK_START.md)** - Legacy endpoint reference
- **[Test API Guide](TEST_API.md)** - Testing examples and validation

### Core APIs  (January 2026)

| API | Documentation | Description |
|-----|---------------|-------------|
| **Memory** | [MEMORY.md](MEMORY.md) | CRUD, search (keyword/semantic), categories |
| **Intel** | [INTEL.md](INTEL.md) | Knowledge base file management (jarvis-intel/) |
| **Query** | [QUERY.md](QUERY.md) | Send text queries to Jarvis programmatically; use `analyze_image` in the query for vision |
| **Workflows** | [WORKFLOWS.md](WORKFLOWS.md) | Execute multi-tool pipelines (e.g., /crypto, /archive) |
| **Conversations** | [CONVERSATIONS.md](CONVERSATIONS.md) | Browse conversation history |
| **Stash** | [STASH.md](STASH.md) | Access stored artifacts and files |
| **Canvas** | [CANVAS.md](CANVAS.md) | Browse visual knowledge pages |
| **Generated Images** | [GENERATED_IMAGES.md](GENERATED_IMAGES.md) | List, download, delete, generate AI images |
| **Images (CDN)** | [API_OVERVIEW.md#images](API_OVERVIEW.md) | Upload to Cloudflare CDN (public URLs) |

### Quick Reference - Core Endpoints

```bash
# Memory
GET  /api/memory              # List memories
POST /api/memory              # Create memory
GET  /api/memory/search/keyword?q=flask    # Keyword search
GET  /api/memory/search/semantic?q=where+is+my+app  # Semantic search

# Intel (Knowledge Base Files)
GET  /api/intel               # List intel files
GET  /api/intel/stats         # Folder statistics
POST /api/intel               # Create intel file
GET  /api/intel/{filename}    # Read file content
PUT  /api/intel/{filename}    # Update file
DELETE /api/intel/{filename}  # Delete file + memories
POST /api/intel/ingest        # Trigger ingestion

# Query
POST /api/query               # Full query with options
POST /api/query/quick         # Simple query {"query": "what time is it"}

# Workflows
GET  /api/workflows           # List available workflows
GET  /api/workflows/{id}      # Get workflow details
POST /api/workflows/{id}/execute  # Execute workflow
GET  /api/workflows/history   # Execution history

# Conversations
GET  /api/conversations       # List conversations
GET  /api/conversations/recent?minutes=30  # Recent conversations
GET  /api/conversations/search?q=weather   # Search history

# Stash
GET  /api/stash               # List stash spaces
GET  /api/stash/space/{space_id}  # Get a space and its files
GET  /api/stash/space/{space_id}/file/{file_id}/download  # Download file

# Canvas
GET  /api/canvas              # List canvas pages
GET  /api/canvas/search?q=status  # Search pages
GET  /api/canvas/{id}         # Get page with content

# Generated Images (Local)
GET  /api/generated-images              # List images
GET  /api/generated-images?search=robot # Search by filename
GET  /api/generated-images/{filename}   # Download image file
GET  /api/generated-images/{filename}/base64  # Get as base64
DELETE /api/generated-images/{filename} # Delete image
POST /api/generated-images/generate     # Generate new image
GET  /api/generated-images/health       # Status check
```

### Intelligence API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/intelligence/stats` | GET | Basic stats (experiences, insights) |
| `/api/intelligence/health` | GET | Health check with issue detection |
| `/api/intelligence/metrics` | GET | Prometheus-style metrics |
| `/api/intelligence/insights` | GET | Recent insights (last 20) |
| `/api/intelligence/experiences` | GET | Recent experiences (last 20) |
| `/api/intelligence/logs/recent` | GET | Today's intelligence logs |
| `/api/intelligence/reflect` | POST | Trigger manual reflection |
| `/api/intelligence/reflections` | GET | List pending reflections |
| `/api/intelligence/reflections/{id}` | DELETE | Cancel specific reflection |
| `/api/intelligence/reflections` | DELETE | Cancel all pending reflections |
| `/api/intelligence/evaluate` | GET | Meta-cognition evaluation |
| `/api/intelligence/maintenance/all` | POST | Run all maintenance jobs |

See **[../INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md)** for full documentation.

### Proactive API (Webhooks)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/alerts` | POST | Receive external alerts |
| `/api/alerts` | GET | List active alerts |
| `/api/alerts/{id}` | DELETE | Dismiss alert |
| `/api/reminders` | GET | List reminders |
| `/health` | GET | API health check |

### Integration & Examples
- **[Code Examples](code-examples/)** - Ready-to-use templates (Python, Node.js, Bash, Docker)
- **[Alert Scenarios](code-examples/ALERT_SCENARIOS.md)** - Complete integration patterns
- **[Remote Monitoring](REMOTE_MONITORING.md)** - Monitor remote servers/containers
- **[Security Options](SECURITY_OPTIONS.md)** - Tailscale, WireGuard, secure access

### Prometheus Metrics
Intelligence metrics exposed at `/metrics`:
```promql
jarvis_intelligence_experiences_total{mode="cloud"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="positive"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="negative"}
jarvis_intelligence_avg_confidence{mode="cloud"}
jarvis_intelligence_pending_reflections{mode="cloud"}
```

### Reference
- **[Fixes Log](../archive/api/FIXES_LOG.md)** - Historical fixes and updates

### Architecture (see `docs/service/`)
- [Proactive System Architecture](../service/PROACTIVE_ASSISTANT_SYSTEM.md)
- [Service Architecture FAQ](../service/SERVICE_ARCHITECTURE_FAQ.md)
- [Phase 1 Complete (historical)](../archive/service/PHASE_1_COMPLETE.md)

---

## Swagger UI

Interactive API documentation available at:

| URL | Description |
|-----|-------------|
| `http://localhost:8880/docs` | Swagger UI (Light mode) |
| `http://localhost:8880/docs/dark` | Swagger UI (Dark mode) ⭐ |
| `http://localhost:8880/redoc` | ReDoc alternative |

---

## Quick Links

| Need | Link |
|------|------|
| **Complete Reference** | [API Overview](API_OVERVIEW.md) |
| **Memory Operations** | [Memory API](MEMORY.md) |
| **Intel Files** | [Intel API](INTEL.md) |
| **Query Jarvis** | [Query API](QUERY.md) |
| **Workflow Pipelines** | [Workflows API](WORKFLOWS.md) |
| **Code Examples** | [code-examples/](code-examples/) |
| **Remote Setup** | [Remote Monitoring Guide](REMOTE_MONITORING.md) |
| **Intelligence Layer** | [INTELLIGENCE_LAYER.md](../INTELLIGENCE_LAYER.md) |
| **Test Everything** | [Test API Guide](TEST_API.md) |

---

## Changelog

### v2.0 (January 2026)
- Added Memory API (CRUD, keyword/semantic search)
- Added Intel API (knowledge base file management)
- Added Query/Chat API (programmatic Jarvis queries)
- Added Conversations API (history browsing)
- Added Stash API (artifact access)
- Added Canvas API (knowledge pages)
- Added Generated Images API (list, download, delete, generate)
- Added Swagger dark mode (`/docs/dark`)
- Added reflection management endpoints
- Added maintenance trigger endpoint

### v1.0 (Original)
- Proactive webhook system
- Alert management
- Intelligence metrics
- Prometheus integration
