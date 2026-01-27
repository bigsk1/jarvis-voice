# Jarvis Intel System 📁🧠

**Status**: ✅ Fully operational  
**Created**: November 12, 2025  
**Purpose**: Knowledge base for storing technical information that Jarvis and OpenCode can access

---

## 🎯 **Overview**

The **Jarvis Intel System** lets you drop technical documents into a folder, and Jarvis automatically extracts and stores key information in its memory database. This solves the problem of verbally dictating IPs, URLs, and technical details through voice recognition.

### Why This Exists

**Problem**: Whisper voice recognition struggles with:
- IP addresses (192.168.70.226 → "one ninety two dot one sixty eight dot seventy dot two twenty six")
- URLs and endpoints
- Technical IDs and hashes
- Network configurations

**Solution**: Write it down once, let Jarvis read and remember it.

---

## 📂 **The `jarvis-intel/` Folder**

### Location
```
/home/boss/jarvis-voice/jarvis-intel/
```

### Security
- **NOT tracked by git** (in `.gitignore`)
- Safe for sensitive data (IPs, credentials, configs)
- Only accessible locally

### What to Store
Drop `.txt` or `.md` files containing:
- 🌐 Network configurations (IPs, VLANs, subnets)
- 🔑 Service URLs and API endpoints
- 📋 Project specifications
- 🛠️ Custom commands and scripts
- 📝 Technical notes
- 🏢 Infrastructure topology

---

## 🚀 **How to Use**

### 1. Add Intel Files

Create a file in `jarvis-intel/`:

```bash
# Example: network_info.md
cat > jarvis-intel/my_servers.md << 'EOF'
# Production Servers

- Database server: 192.168.70.100:5432
- Redis cache: 192.168.70.101:6379
- API gateway: https://api.example.com
- Monitoring: https://grafana.example.com

## Credentials
- DB user: app_user
- API key location: /etc/secrets/api.key
EOF
```

### 2. Tell Jarvis to Ingest

**Via voice**:
```
"Hey Jarvis, ingest intel files"
```

**Via CLI**:
```bash
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

**Direct tool call**:
```bash
python3 skills/ingest_intel.py '{}'
```

### 3. Jarvis Responds

```
"Ingested 1 intel file, extracted 8 facts."
```

### 4. Use the Information

Now Jarvis and OpenCode know about your servers:

```
"Hey Jarvis, what's my database server IP?"
→ "Your database server is at 192.168.70.100 port 5432"

"Use OpenCode to create a script that connects to my Redis cache"
→ OpenCode creates a script using 192.168.70.101:6379
```

---

## 🔧 **How It Works**

### File Processing

1. **Scan folder** → Find all `.txt` and `.md` files (except README.md)
2. **Check hashes** → Compare file MD5 hashes against stored hashes
3. **Clean up deleted** → Remove facts for files that no longer exist on disk
4. **Skip unchanged** → Files with matching hashes are skipped
5. **Extract facts** → Parse key-value pairs and structured data from new/modified files
6. **Save to memory** → Store in MemoryDB with high importance (8/10)
7. **Update hash** → Store new hash for tracking (unique key per file: `intel_hash_{filename}`)
8. **Make available** → Jarvis and OpenCode can now access this info

### Fact Extraction Patterns

The tool recognizes:

**Key-value pairs**:
```
Server IP: 192.168.70.100
Database name: production_db
API endpoint: https://api.example.com
```

**Bullet lists**:
```
- Ollama server: 192.168.70.226:11434
- Main router: 192.168.70.1
```

**Sections** (from markdown headers):
```
## Production Servers

- Web1: 10.0.1.10
- Web2: 10.0.1.11
```

### Automatic Categorization

Facts are categorized by content:

| Keywords | Category | Examples |
|----------|----------|----------|
| ip, host, server, network, vlan | `network` | IPs, hostnames, VLANs |
| password, key, secret, token | `credentials` | API keys, passwords |
| project, repo, code | `project` | Project details |
| (default) | `technical` | General technical info |

---

## 🔍 **Viewing Stored Intel**

### Search Memory

```bash
# Search for specific terms
./bin/jarvis-memory search "ollama"
./bin/jarvis-memory search "192.168"
./bin/jarvis-memory search "api"
```

### Check Ingested Files

```bash
# Direct SQL query to see tracked files and their hashes
sqlite3 data/jarvis_memory.db "SELECT key, value FROM knowledge_base WHERE key LIKE 'intel_hash_%'"

# Or via Python
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()
cursor = db.conn.cursor()
results = cursor.execute(\"SELECT key, value FROM knowledge_base WHERE key LIKE 'intel_hash_%'\").fetchall()
print('📁 Ingested files:')
for r in results:
    filename = r['key'].replace('intel_hash_', '')
    print(f'  • {filename} (hash: {r[\"value\"][:8]}...)')
"
```

### Semantic Search

```bash
# Find related information
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()
results = db.semantic_search('server configurations', limit=5)
for r in results:
    print(f'{r.get(\"key\")}: {r.get(\"value\")[:60]}...')
"
```

---

## 💡 **Advanced Usage**

### Updating Information

Simply edit the file and re-ingest - changes are automatically detected:

```bash
# 1. Edit your intel file
nano jarvis-intel/servers.md

# 2. Re-ingest (automatically detects the changed file)
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

The system compares MD5 hashes and only re-ingests modified files. Old facts from the modified file are automatically deleted before adding the new facts.

### Deleting Information

When you delete an intel file, run ingest to clean up:

```bash
# 1. Delete the file
rm jarvis-intel/old_servers.md

# 2. Run ingest to clean up orphaned facts
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

Response will show:
```
"Cleaned up 1 deleted file (15 facts removed). Skipped 4 unchanged files."
```

### Multiple Files

Organize by topic:

```
jarvis-intel/
├── network_config.md
├── api_endpoints.md
├── server_inventory.md
├── kubernetes_clusters.md
└── credentials.md
```

All files are processed together. Jarvis will report:
```
"Ingested 5 intel files, extracted 42 facts."
```

### Re-running (No Duplicates)

If you run "ingest intel files" again without changes:

```
"All 5 intel files already ingested. Nothing new to add."
```

If files were modified or deleted:
```
"Ingested 2 intel files, extracted 18 facts. Cleaned up 1 deleted file (8 facts removed). Skipped 3 unchanged files."
```

Each file has a unique MD5 hash stored in the database (`intel_hash_{filename}`). This enables:
- **Skip unchanged**: Files with matching hashes are not re-processed
- **Re-ingest modified**: Files with different hashes get their old facts deleted and new facts added
- **Clean up deleted**: Files that no longer exist have their facts removed from the database

---

## 🔗 **Integration with OpenCode**

### How OpenCode Gets Intel

When you ask Jarvis to use OpenCode:

1. **Router detects** → "Use OpenCode to..."
2. **Memory context added** → `get_memory_context()` searches relevant intel
3. **OpenCode receives** → Context includes your network/server info
4. **OpenCode uses it** → Creates scripts with correct IPs/URLs

### Example Flow

**You say**:
```
"Use OpenCode to create a Python script that pings my Ollama server"
```

**What happens**:
1. Jarvis searches memory for "ollama", "server", "ping"
2. Finds: "Ollama AI Server: 192.168.70.226:11434"
3. Passes this to OpenCode in the context
4. OpenCode creates: `ping_ollama.py` with the correct IP

**Result**:
```python
#!/usr/bin/env python3
import requests

OLLAMA_SERVER = "http://192.168.70.226:11434"

response = requests.get(f"{OLLAMA_SERVER}/api/tags")
if response.status_code == 200:
    print("✅ Ollama server is reachable!")
else:
    print(f"❌ Server returned {response.status_code}")
```

---

## 📊 **Current Status**

### Fixed Issues ✅
1. **Memory error fixed** → Removed invalid `provider` parameter from `semantic_search()`
2. **Tool working** → Ingest intel successfully processes files
3. **Smart deduplication** → Per-file MD5 hash tracking (unique key per file)
4. **Change detection** → Only modified files are re-ingested
5. **Cleanup on delete** → Orphaned facts removed when files are deleted
6. **Integration** → OpenCode can access intel via memory context
7. **Cloud/Local mode** → Works correctly in both modes with separate databases

### Example Intel in System ✅

Currently stored (from `example_network.md`):
- Ollama AI Server: 192.168.70.226:11434
- Main router gateway: 192.168.70.1
- Fred workstation: 192.168.70.228
- VLAN 10: IoT devices (192.168.10.0/24)
- VLAN 20: Lab network (192.168.70.0/24)
- Jarvis workspace: /home/boss/jarvis-workspace
- Jarvis codebase: /home/boss/jarvis-voice (protected)
- OpenCode server: port 4096

---

## 🛠️ **Troubleshooting**

### Intel not being recalled

**Issue**: Jarvis says "I don't have that information"

**Fix**: Check if the data was actually ingested:
```bash
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()
results = db.semantic_search('your search term', limit=5)
print(f'Found {len(results)} results')
for r in results:
    print(f'  • {r.get(\"key\")}: {r.get(\"value\")[:60]}...')
"
```

### Server crash

**Issue**: "whole server crashed"

**Possible causes**:
- OpenCode server OOM (large context)
- Long-running task timeout
- Network issue

**Check logs**:
```bash
# OpenCode service status
sudo systemctl status opencode-jarvis

# OpenCode logs
./bin/opencode-logs --verbose

# Restart if needed
sudo systemctl restart opencode-jarvis
```

### Duplicate facts

**Issue**: Same information stored multiple times

**Prevention**: Don't manually edit memory DB, always use the ingest tool

**Fix**: Clear memory and re-ingest:
```bash
# Backup first!
cp data/jarvis_memory.db data/jarvis_memory.db.backup

# Clear intel facts and hashes
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE source LIKE 'intel/%'"
sqlite3 data/jarvis_memory.db "DELETE FROM knowledge_base WHERE key LIKE 'intel_hash_%'"

# Re-ingest
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

### Cloud vs Local Mode

The ingestion system works in both modes with separate databases:

| Mode | Database | Command |
|------|----------|---------|
| Cloud | `data/jarvis_memory.db` | `./orchestrator/orchestrator_v2.py cloud "ingest intel"` |
| Local | `data/jarvis_memory_local.db` | `./orchestrator/orchestrator_v2.py local "ingest intel"` |

**Sync behavior**: If you use a sync script to copy data between databases:
- Sync typically copies data **to** local but doesn't propagate deletions
- Running ingest in local mode will clean up any orphaned facts in the local DB
- Each database maintains independent hash tracking

---

## 📝 **Files & Components**

### New Files Created
- `jarvis-intel/` → Intel storage folder (not in git)
- `jarvis-intel/README.md` → User instructions
- `jarvis-intel/example_network.md` → Example intel file
- `skills/ingest_intel.py` → Tool implementation
- `skills/ingest_intel.tool.json` → Tool schema
- `docs/JARVIS_INTEL_SYSTEM.md` → This documentation

### Modified Files
- `.gitignore` → Added `jarvis-intel/` exclusion
- `skills/opencode.py` → Fixed `semantic_search()` call (removed `provider` param)

---

## 🎯 **Best Practices**

1. **Organize by topic** → Separate files for network, servers, APIs, etc.
2. **Use clear labels** → "Server IP: x.x.x.x" not just "x.x.x.x"
3. **Include context** → "Production database: 192.168.70.100" not just "192.168.70.100"
4. **Keep files updated** → Edit and re-ingest when configs change
5. **Test recall** → After ingesting, verify Jarvis can find the info
6. **Don't duplicate** → The tool handles dedup, but don't create multiple files with same info

---

## 🚀 **Future Enhancements** (Optional)

1. ~~**Smart updates** → Detect file changes, only update modified facts~~ ✅ **IMPLEMENTED** (Jan 2026)
2. ~~**Delete tracking** → Remove facts when intel files are deleted~~ ✅ **IMPLEMENTED** (Jan 2026)
3. **LLM-powered extraction** → Use LLM to extract facts instead of regex
4. **Confidence scores** → Track how certain Jarvis is about each fact
5. **Expiration dates** → Auto-expire old infrastructure info
6. **Conflict resolution** → Detect and merge conflicting information

---

**Status**: ✅ Fully operational and tested  
**Last Updated**: January 27, 2026  
**Maintained by**: Jarvis development team

