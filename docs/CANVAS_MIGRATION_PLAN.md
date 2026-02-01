# Canvas Migration Plan: Monolith → Modular Structure

**STATUS: ✅ COMPLETED** (Feb 2026)

## Previous State

**Single file:** `bin/jarvis-canvas` (3,770+ lines)
- All HTML templates as Python strings
- All CSS embedded in templates
- All JavaScript embedded in templates
- All Flask routes in one file
- Contains both Canvas Pages and Image Gallery

## Integration Points Analysis

### 1. External Entry Point (NO CHANGE NEEDED)

| Reference | File | Impact |
|-----------|------|--------|
| `./bin/jarvis-canvas` | `bin/start` | Entry point stays same |
| `./bin/jarvis-canvas` | `bin/jarvis-dashboard` | Entry point stays same |
| `./bin/jarvis-canvas` | Multiple docs | Just docs, no code change |

**Solution:** Keep `bin/jarvis-canvas` as entry point, just make it import from `jarvis-canvas/`

### 2. Port 8890 References (NO CHANGE NEEDED)

| Reference | File | Purpose |
|-----------|------|---------|
| `localhost:8890` | `skills/canvas.py` | Tool talks to Flask server |
| `localhost:8890` | `bin/jarvis-dashboard` | Health check commands |
| `hostname:8890` | `jarvis-web/client/index.html` | Canvas button link |
| Port 8890 | `bin/start` | Health check |

**Solution:** Port stays 8890, all integrations continue working

### 3. Flask API Endpoints (NO CHANGE NEEDED)

These endpoints are consumed by `skills/canvas.py` and external tools:

| Endpoint | Purpose | Consumers |
|----------|---------|-----------|
| `/api/health` | Health check | skills/canvas.py, bin/start, dashboard |
| `/api/pages` | List/create pages | skills/canvas.py |
| `/api/pages/<id>` | Get/update/delete page | skills/canvas.py |
| `/api/gallery/images` | List images | Image gallery UI |
| `/api/gallery/images/<name>/to-video` | Image→Video | Gallery UI |

**Solution:** Keep all endpoints identical, just move route code to modules

### 4. FastAPI Routes (SEPARATE SYSTEM - NO CHANGE)

| File | Purpose |
|------|---------|
| `api/routes/canvas.py` | Read-only API on port 8880 |

This reads directly from `data/canvas/` files, doesn't talk to Flask server.
**No changes needed.**

### 5. Data Directories (NO CHANGE NEEDED)

| Directory | Purpose |
|-----------|---------|
| `data/canvas/` | Canvas page JSON files |
| `data/generated_images/` | AI-generated images |
| `data/generated_videos/` | AI-generated videos |

**Solution:** Keep same paths, reference via config

---

## Proposed Structure

```
jarvis-canvas/
├── __init__.py
├── app.py                      # Flask app factory
├── config.py                   # Configuration
├── client/
│   ├── static/
│   │   ├── css/
│   │   │   ├── base.css        # Shared styles (dark theme, fonts)
│   │   │   ├── canvas.css      # Canvas pages styles
│   │   │   ├── gallery.css     # Image gallery styles
│   │   │   └── video-gallery.css  # Video gallery styles (NEW)
│   │   └── js/
│   │       ├── canvas.js       # Canvas page logic
│   │       ├── gallery.js      # Image gallery logic
│   │       └── video-gallery.js   # Video gallery logic (NEW)
│   └── templates/
│       ├── base.html           # Shared layout (header, nav)
│       ├── canvas.html         # Canvas pages view
│       ├── gallery.html        # Image gallery view
│       └── video-gallery.html  # Video gallery view (NEW)
├── server/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       ├── health.py           # /api/health
│       ├── pages.py            # /api/pages/* (canvas CRUD)
│       ├── gallery.py          # /api/gallery/images/*
│       └── video_gallery.py    # /api/gallery/videos/* (NEW)
└── README.md

bin/jarvis-canvas                # Entry point (thin wrapper)
```

### Entry Point (`bin/jarvis-canvas`)

After migration, this becomes a thin wrapper:

```python
#!/usr/bin/env python3
"""Jarvis Canvas - Visual content viewer"""
import sys
import os

# Add jarvis-canvas to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_canvas.app import create_app

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    app = create_app()
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)
```

---

## Migration Phases

### Phase 1: Create Directory Structure
- [ ] Create `jarvis-canvas/` directory
- [ ] Create subdirectories: `client/static/css/`, `client/static/js/`, `client/templates/`, `server/routes/`
- [ ] Add `__init__.py` files

**Time:** 5 min | **Risk:** None

### Phase 2: Extract CSS
- [ ] Extract base styles (fonts, colors, dark theme) → `base.css`
- [ ] Extract canvas-specific styles → `canvas.css`
- [ ] Extract gallery-specific styles → `gallery.css`
- [ ] Test styles load correctly

**Time:** 15 min | **Risk:** Low (visual only)

### Phase 3: Extract JavaScript
- [ ] Extract canvas page logic → `canvas.js`
- [ ] Extract image gallery logic → `gallery.js`
- [ ] Test all interactive features work

**Time:** 20 min | **Risk:** Medium (logic bugs)

### Phase 4: Create Jinja Templates
- [ ] Create `base.html` with shared layout (header, nav, footer)
- [ ] Create `canvas.html` extending base
- [ ] Create `gallery.html` extending base
- [ ] Test template rendering

**Time:** 30 min | **Risk:** Medium (template syntax)

### Phase 5: Split Routes
- [ ] Create `server/routes/health.py` - health endpoint
- [ ] Create `server/routes/pages.py` - canvas CRUD
- [ ] Create `server/routes/gallery.py` - image gallery
- [ ] Create `app.py` with Flask app factory
- [ ] Register all blueprints

**Time:** 30 min | **Risk:** Medium (import paths)

### Phase 6: Update Entry Point
- [ ] Modify `bin/jarvis-canvas` to import from `jarvis_canvas.app`
- [ ] Test all endpoints work
- [ ] Test `bin/start` can launch it
- [ ] Test dashboard commands work

**Time:** 10 min | **Risk:** Low

### Phase 7: Add Video Gallery (NEW FEATURE)
- [ ] Create `video-gallery.css`
- [ ] Create `video-gallery.js`
- [ ] Create `video-gallery.html` template
- [ ] Create `server/routes/video_gallery.py`
- [ ] Add route to navigation
- [ ] Test video playback, download, etc.

**Time:** 45 min | **Risk:** Low (new code)

---

## Testing Checklist

After migration, verify:

### Canvas Pages
- [ ] Create page via `skills/canvas.py`
- [ ] View page in browser
- [ ] Edit page
- [ ] Delete page
- [ ] Pin/unpin page
- [ ] Search pages
- [ ] Folder organization works

### Image Gallery
- [ ] `/gallery` loads
- [ ] Images display in grid
- [ ] Lightbox works
- [ ] Search/filter works
- [ ] Download button works
- [ ] CDN upload button works
- [ ] Image-to-video modal works
- [ ] Video generation completes

### Integration
- [ ] `bin/start` launches canvas successfully
- [ ] Health check passes: `curl localhost:8890/api/health`
- [ ] Dashboard "Start Canvas" command works
- [ ] Dashboard health check command works
- [ ] jarvis-web Canvas button (📄) opens canvas
- [ ] FastAPI canvas routes still work (port 8880)

---

## Rollback Plan

If migration fails:
1. Keep original `bin/jarvis-canvas.backup`
2. Restore with: `cp bin/jarvis-canvas.backup bin/jarvis-canvas`
3. Remove `jarvis-canvas/` directory

---

## Benefits After Migration

| Benefit | Impact |
|---------|--------|
| **Easier navigation** | Find CSS without scrolling past 2000 lines of Python |
| **Code reuse** | Share base template/styles across all views |
| **Faster development** | Edit one file without touching others |
| **Better testing** | Test routes independently |
| **Video gallery** | Easy to add as new module |
| **Future features** | Charts, dashboards become straightforward |

---

## Completion Summary

Migration completed successfully on 2026-02-01.

### Final Structure

```
jarvis-canvas/
├── __init__.py
├── config.py                      # Configuration (paths, ports)
├── client/
│   ├── static/
│   │   ├── css/
│   │   │   ├── base.css           # Shared styles
│   │   │   ├── canvas.css         # Canvas pages
│   │   │   ├── gallery.css        # Image gallery
│   │   │   └── video-gallery.css  # Video gallery
│   │   └── js/
│   │       ├── canvas.js          # Canvas pages logic
│   │       ├── gallery.js         # Image gallery logic
│   │       └── video-gallery.js   # Video gallery logic
│   └── templates/
│       ├── base.html              # Shared layout
│       ├── canvas.html            # Canvas pages
│       ├── gallery.html           # Image gallery
│       └── video-gallery.html     # Video gallery
└── server/
    ├── __init__.py
    ├── app.py                     # Flask app factory + run_server()
    ├── pages.py                   # Page storage functions
    ├── utils.py                   # Utility functions
    └── routes/
        ├── __init__.py            # Blueprint registration
        ├── health.py              # /api/health
        ├── pages.py               # /api/pages/*
        ├── gallery.py             # /api/gallery/images/*
        ├── video_gallery.py       # /api/gallery/videos/*
        ├── stash.py               # /api/stash/*
        └── views.py               # / and /gallery, /video-gallery

bin/jarvis-canvas                  # Entry point (59 lines)
```

### Benefits Achieved

- **Code organization:** From 3,770 lines to modular structure
- **Video gallery added:** New feature enabled by refactor
- **Consistency:** Matches jarvis-web, jarvis-memory, jarvis-intelligence patterns
- **Maintainability:** Easy to add new features or modify existing ones

---

**Version:** 2.0  
**Created:** 2026-02-01  
**Completed:** 2026-02-01
