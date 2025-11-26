# Auto Mode - Smart Adaptive Response Formatting


![speech-modes-info-graph](images/speech-modes-info-graph.jpeg)
---

## The 3 Modes Explained

### 1. `JARVIS_RESPONSE_STYLE="casual"` (DEFAULT - Best for Voice)
**Always** condenses responses to 8-12 words for voice output.

**Examples**:
```
"What time is it?" 
→ "It's 12:34 AM on November 13th"  (8 words)

"Start the tetris server"
→ "Tetris server started successfully with PID 128712"  (8 words)

"Build me a website with dark mode and user login"
→ "Website built with dark mode and login system"  (9 words)
```

**When to use**: Voice mode (default) - everything spoken through speakers should be concise.

---

### 2. `JARVIS_RESPONSE_STYLE="detailed"` (Best for CLI/Debugging)
**Always** uses full LLM response with complete context.

**Examples**:
```
"What time is it?"
→ "The current time is 12:34 AM on Wednesday, November 13th, 2025. 
   I've retrieved this information from the system clock."

"Start the tetris server"
→ "The tetris server has been successfully started!

   Here's what was done:
   1. Located project at ~/jarvis-workspace/projects/tetris-game/
   2. Activated Python virtual environment
   3. Started Flask server in background (PID: 128712)
   4. Verified server responding on port 5000
   
   Server accessible at http://192.168.70.228:5000"

"Build me a website with dark mode and user login"
→ "I've successfully completed building your website! Here's what was created:

   Components:
   - Full dark mode theme with CSS variables
   - User authentication system (login/register)
   - JWT token-based session management
   - Responsive design for mobile/desktop
   - SQLite database for user storage
   
   Files created:
   - server.py (Flask backend)
   - templates/ (HTML pages)
   - static/css/dark-theme.css
   - static/js/auth.js
   
   The server is running on port 3000..."
```

**When to use**: CLI testing, debugging, log review - when you need full technical context.

---

### 3. `JARVIS_RESPONSE_STYLE="auto"` ⭐ (NEW - Smart Adaptive)
**Intelligently decides** based on tool type and complexity.

#### **Auto Mode Logic**:

```python
# Search tools → Always format for voice
if tool in ['search_memory', 'duckduckgo_search', 'recall', 'semantic_recall']:
    return FORMATTED_SHORT  # Remove URLs, summarize

# Simple data tools → Keep concise (if already short)
elif tool in ['get_time', 'crypto_price', 'get_weather']:
    if response_length <= 20 words:
        return AS_IS  # Already short, keep it
    else:
        return FORMATTED_SHORT  # Condense

# Complex/action tools → Adaptive based on response length
elif tool in ['opencode', 'execute_bash', 'send_webhook']:
    if response_length > 50 words:
        return DETAILED  # Keep full context for complex operations
    else:
        return FORMATTED_SHORT  # Condense simple results

# Multi-turn (multiple tools) → Always format summary
if turn_num > 0:
    return FORMATTED_SUMMARY
```

#### **Auto Mode Examples**:

**Simple Query (Short Response)**:
```
"What time is it?"  
Tool: get_time
Response length: 8 words
→ "It's 12:34 AM on November 13th"  (condensed)
```

**Search Query (Always Formatted)**:
```
"Search memory for webhook info"
Tool: search_memory  
→ "Found 3 webhook memories: URL, logger endpoint, and server port"  
   (formatted for voice, URLs removed)

"Use DuckDuckGo to find movies in Hillsboro"
Tool: mcp_duckduckgo_search
→ "Found 5 theaters showing latest movies. Regal Cinemas has evening showtimes..."
   (formatted for voice, URLs removed, summarized)
```

**Simple Action (Short Response)**:
```
"Start the tetris server"
Tool: execute_bash (then search_memory)
Response length: ~15 words
→ "Tetris server started on port 5000"  (condensed)
```

**Complex Build (Detailed Response)**:
```
"Build me a complete e-commerce website with user login, dark mode, shopping cart, and payment integration"
Tool: opencode
Response length: 80+ words (detailed technical response)
→ FULL DETAILED RESPONSE (kept as-is because >50 words)

   "I've successfully built your e-commerce website with all requested features:

   Architecture:
   - Flask backend with Blueprint structure
   - SQLAlchemy ORM for database
   - JWT authentication for user sessions
   - Stripe payment integration
   - Dark mode theme with CSS variables
   
   Features implemented:
   1. User registration and login system
   2. Product catalog with search/filter
   3. Shopping cart with session persistence
   4. Checkout flow with Stripe
   5. Dark mode toggle (persists in localStorage)
   
   Files created (23 total):
   - server.py (main Flask app)
   - models/ (User, Product, Order, Cart)
   - routes/ (auth, products, cart, payment)
   - templates/ (12 HTML pages)
   - static/css/dark-theme.css
   - static/js/cart.js, auth.js, theme-toggle.js
   
   Database: SQLite (ready for PostgreSQL upgrade)
   Server running on: http://localhost:5000
   Admin panel: http://localhost:5000/admin
   
   Next steps:
   - Configure Stripe API keys in .env
   - Add product images to static/images/
   - Test checkout flow with Stripe test cards"
```

**Multi-Turn (Always Formatted)**:
```
"Start the tetris server and save the URL to memory"
Turn 1: search_memory → find instructions
Turn 2: execute_bash → start server
Turn 3: execute_bash → verify running
Turn 4: remember → save URL
→ "Tetris server started on port 5000, URL saved to memory"  
   (always formatted for multi-turn)
```

---

## **When to Use Each Mode**

| Mode | Best For | Response Style |
|------|----------|----------------|
| **casual** | Voice mode (default) | Always 8-12 words |
| **detailed** | CLI, debugging, logs | Always full context |
| **auto** | Mixed usage, smart assistant | Adapts based on tool/complexity |

---

## **Your Original Idea Was Perfect!**

You asked:
> "Build me a website...response in auto longer?"

**YES!** In auto mode:
- ✅ Simple tasks → Short responses
- ✅ Complex builds (>50 words) → Detailed responses
- ✅ Search queries → Always formatted (no URLs)
- ✅ Multi-turn operations → Formatted summaries

**Auto mode gives you the best of both worlds!**

---

## **How to Enable Auto Mode**

### Option 1: Set in config (permanent)
```bash
# Edit config/cloud.env
JARVIS_RESPONSE_STYLE="auto"
```

### Option 2: Env var override (one-off testing)
```bash
JARVIS_RESPONSE_STYLE=auto ./jarvis
# or
JARVIS_RESPONSE_STYLE=auto python3 orchestrator/orchestrator_v2.py cloud "query"
```

---

## **Implementation Details**

### Tool Categories:

**Search Tools** (always formatted):
- `search_memory`
- `semantic_recall`
- `recall`
- `mcp_duckduckgo_search`
- `mcp_fetch_fetch`

**Simple Tools** (keep short if <20 words):
- `get_time`
- `crypto_price`
- `get_weather`

**Complex Tools** (adaptive based on length):
- `opencode` (detailed if >50 words)
- `execute_bash` (detailed if >50 words)
- `send_webhook`
- `api_call`

**Multi-Turn** (always formatted):
- Any operation using 2+ tools

---

## **Testing Auto Mode**

```bash
# Simple query - should be short
JARVIS_RESPONSE_STYLE=auto python3 orchestrator/orchestrator_v2.py cloud "what time is it"

# Search query - should be formatted (no URLs)
JARVIS_RESPONSE_STYLE=auto python3 orchestrator/orchestrator_v2.py cloud "search memory for webhook"

# Simple action - should be short
JARVIS_RESPONSE_STYLE=auto python3 orchestrator/orchestrator_v2.py cloud "start tetris server"

# Complex build - should be detailed (if response >50 words)
JARVIS_RESPONSE_STYLE=auto python3 orchestrator/orchestrator_v2.py cloud "use opencode to build a complete flask API with authentication"
```

---

## **Why This Is Better Than Original**

**Original idea** (from cloud.env comment):
> "auto: Smart mode - format search results, keep other tools raw"

**Problem**: Too simplistic. "Keep other tools raw" means:
- Simple queries (time, crypto) → Verbose ❌
- Complex builds → Verbose ✅
- Multi-turn → Inconsistent ❌

**New auto mode**:
- Search tools → Formatted ✅
- Simple tools → Smart (short if possible) ✅
- Complex tools → Adaptive (detailed only if needed) ✅
- Multi-turn → Formatted summaries ✅

**Result**: Truly intelligent mode that adapts to context!

---

## **Summary**

- ✅ **casual**: Always short (voice mode default)
- ✅ **detailed**: Always verbose (CLI debugging)
- ✅ **auto**: Smart adaptive (your idea, now implemented!)

**Your intuition was spot-on!** Auto mode now:
- Keeps simple things short
- Keeps complex things detailed
- Formats searches for voice
- Adapts based on what makes sense

---

*Last updated: 2025-11-13*  
*Feature requested by: User during voice mode testing*

