# Quick Start: Jarvis Intel System 🚀

## What Is This?

Drop technical info into `jarvis-intel/` folder → Jarvis reads and remembers it → Both Jarvis and OpenCode can use it.

**Problem solved**: No more verbally dictating IPs/URLs through Whisper voice recognition!

---

## 3-Step Usage

### 1. Create Intel File
```bash
cat > jarvis-intel/my_info.md << 'EOF'
# My Setup

- Production server: 192.168.1.100
- API endpoint: https://api.example.com
- Database: db.example.com:5432
EOF
```

### 2. Ingest (Voice or CLI)
```bash
# Voice
"Hey Jarvis, ingest intel files"

# CLI
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

### 3. Use It
```bash
# Ask Jarvis
"What's my production server IP?"
→ "Your production server is at 192.168.1.100"

# With OpenCode
"Use OpenCode to create a script that connects to my database"
→ Creates script with db.example.com:5432
```

---

## Key Features

- ✅ **Auto-dedup**: Won't save same info twice
- ✅ **Not in git**: Safe for sensitive data
- ✅ **Auto-categorize**: network/credentials/project/technical
- ✅ **OpenCode integration**: Automatically receives context
- ✅ **Semantic search**: Finds related info intelligently

---

## Example Intel File

```markdown
# Production Infrastructure

## Web Servers
- Web1: 10.0.1.10
- Web2: 10.0.1.11
- Load balancer: 10.0.1.5

## Databases
- Primary: db1.prod.com:5432
- Replica: db2.prod.com:5432

## APIs
- Main API: https://api.prod.com
- Admin API: https://admin.prod.com
- Health check: https://api.prod.com/health

## Credentials
- DB user: app_production
- API key location: /etc/secrets/prod_api.key
- Vault URL: https://vault.prod.com

## Notes
- Use HTTPS for all external APIs
- Database backups run at 2 AM daily
- Redis cache: cache.prod.com:6379
```

---

## Files

- **Location**: `/home/boss/jarvis-voice/jarvis-intel/`
- **Formats**: `.txt` or `.md` (except README.md)
- **Security**: Not tracked by git ✅
- **Tool**: `skills/ingest_intel.py`

---

## Troubleshooting

### Check what's stored
```bash
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()
results = db.semantic_search('your search term', limit=5)
for r in results:
    print(f'{r.get(\"key\")}: {r.get(\"value\")[:60]}...')
"
```

### Re-ingest if needed
```bash
# Edit your file
nano jarvis-intel/my_info.md

# Re-run ingest (will detect changes by hash)
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

---

## Full Documentation

- **Intel System Guide**: `docs/JARVIS_INTEL_SYSTEM.md`
- **Q&A**: `docs/QUESTIONS_ANSWERED.md`
- **OpenCode Integration**: `docs/OPENCODE_PHASE2_COMPLETE.md`

---

**Status**: ✅ Fully operational  
**Last Updated**: November 12, 2025

