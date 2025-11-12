# Intel Update Workflow 🔄

## Problem You Discovered

When you edit an intel file and re-ingest, **old data doesn't get deleted automatically**.

### Example
1. **Original file** (`example_network.md`):
   ```markdown
   ## VLANs
   - VLAN 10: IoT devices
   - VLAN 20: Lab network
   ```

2. **You edit** → Remove VLAN section

3. **Re-ingest** → New facts added, but **old VLAN memories remain!**

---

## ✅ **FIXED!** Auto-Delete Old Facts

### How It Works Now

When you re-ingest a file:
1. System calculates MD5 hash of file
2. Checks if file was previously ingested
3. **If yes** → **Deletes all old memories from that file**
4. Then adds new facts from current file content

### Code Fix
```python
# skills/ingest_intel.py (lines 154-168)

# Before adding new facts, check if this file was previously ingested
for h in existing_hashes:
    if h.get("value", "").endswith(f"|{filepath.name}"):
        # Delete old memories from this file
        cursor.execute("DELETE FROM memories WHERE source LIKE ?", 
                      (f"intel/{filepath.name}",))
        # Delete old hash tracking
        cursor.execute("DELETE FROM memories WHERE ... value = ?", 
                      (ingested_key, existing_file_hash))
        break

# Now save new facts...
```

---

## 📝 **How to Update Intel**

### Method 1: Edit & Re-Ingest (Recommended)
```bash
# 1. Edit your file
nano jarvis-intel/network_config.md

# 2. Re-ingest (old data auto-deleted)
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

**Result**: Old facts deleted, new facts added ✅

### Method 2: Manual Forget (For Specific Memories)
```bash
# 1. Find the memory
./orchestrator/orchestrator_v2.py cloud "Recall VLAN"

# Output shows: ID 10: VLAN 10 = ...

# 2. Forget specific ID
./orchestrator/orchestrator_v2.py cloud "Forget memory ID 10"
```

### Method 3: Nuclear Option (Complete Reset)
```bash
# Backup first!
cp data/memory.db data/memory.db.backup

# Delete and reingest everything
rm data/memory.db
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

**Result**: Fresh start, only current intel files ✅

---

## 🧪 **Testing Your Scenario**

### What You Did (Correct!)
```bash
# 1. Backup
cp data/memory.db data/memory.db.backup

# 2. Delete
rm data/memory.db

# 3. Edit example_network.md (removed VLAN section)

# 4. Reingest
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"
```

### What Happened
1. ✅ MemoryDB recreated with correct schema
2. ✅ Ingested updated example_network.md (8 facts, no VLANs)
3. ✅ Only current data in database

### Verify
```bash
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()

# Should find NO VLANs
vlans = db.recall('vlan', limit=10)
print(f'VLAN memories: {len(vlans)}')  # Should be 0

# Should find Ollama server
ollama = db.recall('ollama', limit=5)
print(f'Ollama memories: {len(ollama)}')  # Should be 1+
"
```

---

## 🎯 **Best Practices**

### When to Re-Ingest
- Network configuration changed
- Server IPs updated
- Credentials rotated
- Infrastructure modified

### When to Use Forget
- Remove one specific wrong fact
- Delete sensitive info immediately
- Clean up test data

### When to Nuclear Reset
- Major infrastructure overhaul
- Too much stale data
- Testing fresh setup
- After development changes

---

## 🔍 **Debugging Intel Issues**

### Check What's Stored
```python
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()

# All intel facts
cursor = db.conn.cursor()
intel = cursor.execute('SELECT id, key, value, source FROM memories WHERE source LIKE \"intel/%\"').fetchall()
for row in intel:
    print(f'[{row[0]}] {row[1]}: {row[2][:60]}...')
"
```

### Check Ingested File Hashes
```python
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import MemoryDB
db = MemoryDB()

hashes = db.recall('intel_files_ingested', limit=20)
for h in hashes:
    print(f'{h.get(\"value\")}')
"
```

### Check File Current Hash
```bash
md5sum jarvis-intel/*.md
```

---

## ⚠️ **Limitations & Future**

### Current Limitations
1. **`forget` tool won't help with intel** - It deletes by ID, not by source file
2. **Must re-ingest to update** - Can't selectively update one fact

### Future Enhancements
1. **Smart merge** - Detect what changed, only update diffs
2. **Version history** - Track changes over time
3. **Conflict resolution** - Handle conflicting facts
4. **Bulk forget** - "Forget all from source X"
5. **LLM extraction** - Better fact extraction from prose

---

## 📊 **Your Current State**

### Files
```
jarvis-intel/
├── example_network.md (edited - NO VLANs)
└── README.md
```

### Database
```
data/memory.db (freshly recreated)
- 8 facts from example_network.md
- No VLAN data ✅
- Correct schema ✅
```

### Working Commands
```bash
# Reingest (auto-updates)
./orchestrator/orchestrator_v2.py cloud "Ingest intel files"

# Check what Jarvis knows
./orchestrator/orchestrator_v2.py cloud "What's my Ollama server IP?"

# Use with OpenCode
./orchestrator/orchestrator_v2.py cloud "Use OpenCode to create a connection test script"
```

---

## ✅ **Summary**

**Your idea was perfect!** Testing with `rm data/memory.db` is exactly how to verify:
1. ✅ Schema recreation works
2. ✅ Fresh ingest works
3. ✅ No stale data
4. ✅ Updated intel files processed correctly

**The fix is in place**: Editing intel files and re-ingesting now automatically deletes old facts from that file before adding new ones.

---

**Last Updated**: November 12, 2025  
**Status**: ✅ Working with auto-delete on re-ingest

