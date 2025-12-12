# Blinko Integration for Jarvis

> **AI-Powered Note-Taking System with RAG Search**

[Official Site](https://blinko.space) | [Docs](https://docs.blinko.space/) | [API Reference](https://blinko.apidocumentation.com/reference) | [GitHub](https://github.com/blinkospace/blinko)

---

## 🎯 What is Blinko?

Blinko is a self-hosted, AI-powered card-based note-taking system with:
- 🤖 **AI RAG Search** - Semantic search using embeddings
- 📱 **Multi-platform** - Web, macOS, Windows, Android, Linux apps
- 🔒 **Self-hosted** - Your data stays on your server
- ✍️ **Markdown Support** - Rich formatting with MD rendering
- 🗂️ **Card Organization** - Tags, categories, visual layout

---

## 🧠 AI Features & LLM Provider

### What AI Does Blinko Use?

**Embeddings for RAG Search:**
- Uses **OpenAI's `text-embedding-3-small`** (default)
- Alternatives: Can be configured for other embedding models
- Purpose: Semantic search through your notes using natural language

**LLM for Chat/Summaries:**
- Uses **OpenAI models** (default: `gpt-4o-mini` or `gpt-4o`)
- Purpose: AI chat assistant that can search and summarize notes
- Optional: You can skip this if you only want note storage

### Do You Need OpenAI?

**For Basic Note-Taking:**
- ❌ NO - Blinko works fine without AI
- Regular text search still available
- All note-taking features work

**For AI-Powered Search:**
- ✅ YES - Need OpenAI API key for embeddings
- Enables semantic search ("find notes about X" in natural language)
- RAG (Retrieval-Augmented Generation) for better results

**Cost Estimate:**
- `text-embedding-3-small`: ~$0.02 per 1M tokens
- Very cheap - probably $0.50-2/month for personal use
- Only charges when creating/searching notes

---

## 📦 Setup

### Quick Start

```bash
cd blinko/
./install.sh
```

This will:
1. ✅ Generate secure passwords
2. ✅ Pull Docker image
3. ✅ Create data directories
4. ✅ Start Blinko + PostgreSQL

### Manual Setup

```bash
# 1. Create .env file
cp .env.example .env
# Edit .env and set your passwords

# 2. Start services
docker-compose up -d

# 3. Check status
docker-compose ps

# 4. View logs
docker-compose logs -f blinko-app
```

---

## 🔧 Configuration

### Environment Variables

Edit `docker-compose.yml` or `.env`:

```yaml
# Timezone
TZ: America/New_York  # Change to your timezone

# OpenAI (optional - for AI features)
OPENAI_API_KEY: sk-your-key-here
OPENAI_MODEL: gpt-4o-mini
EMBEDDING_MODEL: text-embedding-3-small
```

### Volume Mounts

```yaml
volumes:
  # Blinko data (attachments, uploads)
  - ./data:/app/.blinko
  
```

---

## 🌐 Access

**Web UI:** http://localhost:1111

**First Login:**
- First user to register becomes admin
- Recommended: Create account immediately after install

**API Endpoint:** http://localhost:1111/api/v1

---

## 🔐 API Authentication

### Get API Key

1. Login to Blinko UI
2. Go to Settings → API
3. Generate API key
4. Add to Jarvis config:

```bash
# config/cloud.env or config/local.env
BLINKO_BASE_URL="http://localhost:1111"
BLINKO_API_KEY="your-api-key-here"
```

---

## 📚 Jarvis Integration

### Status

- ✅ **Installation ready** - Docker setup complete
- ⏸️ **Tool creation** - See `docs/BLINKO_INTEGRATION_IDEAS.md`
- ⏸️ **Testing phase** - Evaluate for 1-2 weeks before coding

### Integration Plan

**Phase 1: Manual Evaluation** (Current)
- Use Blinko UI manually
- Test AI search features
- Determine if it fits workflow

**Phase 2: Minimal Tool** (If valuable)
- Create `blinko_notes` tool (4 operations)
- Voice-enable: "Save to Blinko..."
- Search integration

See full plan: `../docs/BLINKO_INTEGRATION_IDEAS.md`

---

## 🛠️ Management

### Common Commands

```bash
# Status
docker-compose ps

# Logs
docker-compose logs -f blinko-app
docker-compose logs -f blinko-postgres

# Restart
docker-compose restart

# Stop
docker-compose down

# Stop and remove data (CAREFUL!)
docker-compose down -v
```

### Backup

```bash
# Backup PostgreSQL database
docker exec blinko-postgres pg_dump -U blinko_user blinko_db > backup.sql

# Backup data folder
tar -czf blinko-data-backup.tar.gz data/

# Restore
cat backup.sql | docker exec -i blinko-postgres psql -U blinko_user -d blinko_db
```

---

## 🔍 AI Feature Details

### RAG (Retrieval-Augmented Generation)

**How it works:**
1. When you create a note → Blinko generates embedding via OpenAI
2. When you search → Query is embedded, semantic search finds similar notes
3. Results ranked by relevance (cosine similarity)
4. Optional: LLM summarizes results

**Benefits:**
- Natural language search ("find my notes about Docker networking")
- Understands context and meaning
- Better than keyword search for conceptual queries

**Limitations:**
- Requires OpenAI API (costs money)
- Embeddings stored in PostgreSQL (vector extension)
- Slower than keyword search (but more accurate)

---

## 📊 System Requirements

- **Docker**: 20.10+
- **Docker Compose**: 2.0+
- **RAM**: 512MB minimum, 1GB recommended
- **Disk**: ~500MB for Docker images + your notes
- **Network**: Port 1111 available

---

## 🐛 Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs blinko-app

# Common issues:
# 1. Port 1111 already in use
# 2. Database not ready (wait 30s)
# 3. Permissions on data folders
```

### Database Connection Failed

```bash
# Check PostgreSQL status
docker-compose ps

# Restart database
docker-compose restart blinko-postgres

# Check connection
docker exec blinko-postgres pg_isready -U blinko_user -d blinko_db
```

### AI Features Not Working

```bash
# Check if OpenAI API key is set
docker-compose exec blinko-app env | grep OPENAI

# Verify in .env file
cat .env

# Restart after adding API key
docker-compose restart blinko-app
```

---

## 🗑️ Uninstall

```bash
# Stop and remove containers
docker-compose down

# Remove data (CAREFUL - this deletes all notes!)
rm -rf data/ postgres-data/

# Remove .env
rm .env
```

---

## 📝 Notes

- **Data Location**: `./data/` and `./postgres-data/`
- **Logs**: `docker-compose logs -f`
- **Updates**: `docker pull blinkospace/blinko:latest && docker-compose up -d`
- **Docs Mount**: Jarvis `docs/` folder mounted read-only at `/app/docs`

---

## 🔗 Links

- [Blinko Integration Ideas](../docs/BLINKO_INTEGRATION_IDEAS.md)
- [Official Documentation](https://docs.blinko.space/)
- [API Reference](https://blinko.apidocumentation.com/reference)
- [GitHub Repository](https://github.com/blinkospace/blinko)
- [Live Demo](https://demo.blinko.space) (username: blinko, password: blinko)

