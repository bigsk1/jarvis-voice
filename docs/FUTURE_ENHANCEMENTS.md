# Jarvis Roadmap & Future Enhancements

This document tracks completed features and planned improvements for Jarvis.

## ✅ Recently Completed

### Intelligent Memory System (v1.0)
- ✅ SQLite database with knowledge_base and conversations tables
- ✅ 5 memory tools (remember, recall, search, semantic_recall, forget)
- ✅ Vector embeddings for semantic search (OpenAI + Ollama)
- ✅ Automatic conversation logging
- ✅ Proactive learning (LLM decides what to remember)
- ✅ Update and correction capabilities

### MCP (Model Context Protocol) Integration (v1.0)
- ✅ Docker-based MCP server support
- ✅ DuckDuckGo web search integration
- ✅ Fetch tool for URL content extraction
- ✅ 3-phase startup sequence (start, wait, discover)
- ✅ Graceful failure handling
- ✅ Tool name normalization for provider compatibility

### Natural Response Formatting (v1.0)
- ✅ `JARVIS_RESPONSE_STYLE` configuration (casual/detailed/auto)
- ✅ LLM-powered response interpretation
- ✅ Voice-optimized output (no URLs unless asked)
- ✅ Conversational follow-up questions
- ✅ Works with all tools and MCP servers

### Tool System Infrastructure (v1.0)
- ✅ Provider-agnostic tool calling (OpenAI, Anthropic, Ollama)
- ✅ Universal tool schema
- ✅ Permission system (dangerous, bash, network, filesystem)
- ✅ Tool call logging with JSONL format
- ✅ Error recovery with retry logic
- ✅ JSON mode for shell script integration

## 🔨 In Progress / Near Term

### 1. Verbal Confirmation Loop
**Priority:** High  
**Status:** Designed, not implemented

Currently tools with `auto_approve: false` execute with a console warning.

**Goal:** Voice-based approval for dangerous operations.

```
You: "Delete all my files"
Jarvis: "This will execute a bash command. Do you approve?"
You: "Yes, I approve"
Jarvis: "Okay, executing... Done."
```

**Implementation:**
- Detect confirmation requirement
- Speak warning
- Record user response
- Check for approval phrases
- Execute or cancel

**Files to modify:**
- `orchestrator/executor.py` - Add confirmation flow
- `bin/confirm.sh` - Record and transcribe approval

### 2. Tool Discovery Optimization -  DONE! ✅
**Priority:** Medium  
**Status:** Design phase

**Problem:** With many tools, sending all tool schemas to LLM is expensive.

**Solution:** Embedding-based tool search
1. Create embeddings for each tool description
2. On user query, find most relevant 10-15 tools
3. Only send relevant tools to LLM
4. Fallback to full list if uncertain

**Benefits:**
- Faster responses (less context)
- Lower API costs
- Scales to 100+ tools

**Implementation:**
```python
# At startup
tool_embeddings = {tool.name: embed(tool.description) for tool in tools}

# Per query
query_embedding = embed(user_query)
relevant_tools = find_similar(query_embedding, tool_embeddings, top_k=15)
```

### 3. Multi-Session Context -  DONE! ✅
**Priority:** Medium  
**Status:** Concept

**Goal:** Remember conversation context across wake word activations.

Currently each "Hey Jarvis" starts fresh. Jarvis should:
- Remember what you just talked about
- Handle follow-up questions
- Maintain context for ~5-10 minutes

**Example:**
```
You: "Hey Jarvis, search for restaurants in Portland"
Jarvis: "I found several great restaurants..."

[30 seconds later]

You: "Hey Jarvis, what about the Italian ones?"
Jarvis: "From the Portland restaurants, here are the Italian options..."
```

**Implementation:**
- Session ID tied to time window
- Load recent conversation from memory DB
- Include in LLM context
- Expire after idle timeout

## 🚀 Future / Nice to Have

### 4. Smart Home Integration
**Priority:** Medium  
**Requires:** Home Assistant or similar

```
You: "Turn on the living room lights"
You: "Set temperature to 72 degrees"
You: "Is the garage door open?"
```

**Tools needed:**
- `home_assistant_control`
- `hass_state_check`
- Device discovery

### 5. Calendar & Reminder System -  DONE! ✅
**Priority:** Medium

```
You: "Remind me to call John at 3 PM"
You: "What's on my calendar tomorrow?"
You: "Schedule a meeting for next Tuesday"
```

**Requirements:**
- CalDAV integration or local calendar - gogle calander integration via n8n
- Background reminder daemon
- Natural language time parsing

### 6. Email Integration -  DONE! ✅
**Priority:** Low
**Complexity:** High

```
You: "Check my email"
You: "Send an email to John about the meeting"
You: "Any unread messages?"
```

### 7. Multi-User Support
**Priority:** Low

**Goal:** Recognize different users, separate memories.

**Challenges:**
- Voice identification
- Per-user configuration
- Privacy implications

**Implementation:**
- Voice fingerprinting (optional)
- Named profiles
- User-scoped memory tables

### 8. Memory Improvements

#### 8.1. Bulk Embedding Regeneration -  DONE! ✅
```bash
# Currently embeddings only created at remember()
# Need tool to regenerate all embeddings after config changes

./bin/sync-memory-db.py --from cloud --to local
```

#### 8.2. Memory Expiration
```python
# Auto-expire old memories
remember("I'm going to the store", importance=3, expires_in="2 hours")
```

#### 8.3. Memory Categories
More structured categories:
- facts (permanent)
- preferences (updateable)
- temporary (auto-expire)
- instructions (how to do things)

#### 8.4. Memory Visualization
Simple web UI to:
- Browse all memories
- Edit/delete manually
- See conversation history
- Export/import

### 9. Advanced MCP Features

#### 9.1. More MCP Servers
- Filesystem operations
- Database queries
- Cloud service integrations (AWS, GCP, etc.)
- GitHub/Git operations

#### 9.2. MCP Tool Composition
Chain multiple MCP tools:
```
You: "Search for the latest AI paper and summarize it"
# Uses: search → fetch → summarize (3 tools)
```

#### 9.3. MCP Performance Optimization
- Keep containers warm (don't restart every time)
- Connection pooling
- Parallel tool execution

### 10. Developer Tools

#### 10.1. Tool Testing Framework
```bash
# Unit tests for each tool
./bin/test-tools --all
./bin/test-tools crypto_price

# Integration tests
./bin/test-integration
```

#### 10.2. Tool Marketplace
- Share tools with community
- Download tools from repository
- Automatic updates

#### 10.3. Tool IDE
Visual tool builder:
- Drag-and-drop schema creation
- Test interface
- Permission configuration

### 11. Performance & Reliability

#### 11.1. Caching
- Cache API responses (crypto prices, web search)
- Cache LLM responses for repeated queries
- Reduce external API calls

#### 11.2. Offline Fallbacks
- Detect when cloud APIs are down
- Auto-switch to local alternatives
- Graceful degradation

#### 11.3. Health Monitoring
```bash
# System health dashboard
./bin/jarvis-health

# Shows:
- LLM provider status
- MCP server health
- Database integrity
- Audio device status
```

### 12. Voice Improvements

#### 12.1. Custom Wake Words
- Train your own wake word
- Multiple wake words for different modes
- Family member-specific wake words

#### 12.2. Voice Cloning
- Clone your voice for TTS
- Sound like you giving commands

#### 12.3. Emotion Detection
- Detect urgency, frustration, happiness
- Adjust responses accordingly
- Faster response for urgent requests

## 📊 Implementation Priority

**High Priority (Next Sprint):**
1. Verbal Confirmation Loop
2. MCP Performance (keep containers warm)
3. Memory bulk operations

**Medium Priority (Next Month):**
1. Tool Discovery Optimization
2. Multi-Session Context
3. Smart Home Integration (if you have devices)

**Low Priority (Future):**
1. Multi-User Support
2. Email Integration
3. Advanced visualizations

## 🤝 Contributing

Want to implement something? Here's how:

1. Pick a feature from this list
2. Create a feature branch
3. Implement with tests
4. Update documentation
5. Test locally
6. Commit with clear messages

## 📝 Notes

- Focus on voice-first experience
- Keep it local-first (privacy)
- Provider-agnostic when possible
- Well-documented and tested
- Backward compatible

---

**Last Updated:** 2025-11-11
**Version:** 1.0 (Memory + MCP + Natural Responses)
