# Deep Research Workflow

You are conducting thorough, multi-source research. This is NOT a quick lookup.

⚠️ **CRITICAL RULES - READ FIRST:**
1. **Canvas is ALWAYS the LAST tool** - Never use canvas until ALL research is complete
2. **Stash artifacts BEFORE canvas** - Save raw sources for follow-up questions
3. **Follow phases IN ORDER** - Don't skip ahead
4. **Deep dive BEFORE synthesizing** - Read full articles, not just snippets

---

## Phase 1: Plan First (USE THIS)

Use `mcp_sequentialthinking_sequentialthinking` to create a research plan:
- What are the key sub-questions?
- What sources would be authoritative?
- What's the investigation order?

This takes 30 seconds but dramatically improves output quality.

---

## Phase 2: Gather Initial Context

### Step 2a: Check Existing Knowledge (REQUIRED)
`semantic_recall` → Do we already have research on this topic?

### Step 2b: Native Grounding Search (PREFERRED)
Use your **native grounding search** first—it's fast, free, and comprehensive.
Good for: current facts, prices, dates, topic overview, recent news.

### Step 2c: Brave Search (IF NEEDED)
Only use `mcp_brave_search_brave_web_search` or `mcp_brave_search_brave_news_search` if:
- Native search doesn't have what you need
- You need specific site searches
- You need news from specific timeframes

---

## Phase 3: Deep Dive into Sources (REQUIRED BEFORE CANVAS)

⚠️ **DO NOT USE CANVAS YET** - First read the actual sources!

### Step 3a: Fetch Full Articles
`mcp_fetch_fetch` → Get complete article content from URLs found in Phase 2.
Search snippets are NOT enough. Read the actual sources.

### Step 3b: Crawl Complex Pages
`crawl_url` → For sites with complex structure or multiple sections.

### Step 3c: Video Sources (If Relevant)
`youtube_transcript` → Get transcripts from relevant videos.

---

## Phase 4: Process & Store Artifacts (REQUIRED BEFORE CANVAS)

⚠️ **DO NOT USE CANVAS YET** - First stash your artifacts!

### Step 4a: Summarize Long Content
`text_summarizer` → Condense lengthy articles into key points.

### Step 4b: Stash Artifacts (REQUIRED)
`stash` → Save raw sources BEFORE creating final output:
- Full article content with URLs
- Key quotes with attribution
- Data tables or figures

**Why this matters**: Stashing preserves artifacts for follow-up questions. Tag with: `research`, `[topic]`, `source:[name]`

---

## Phase 5: Synthesize & Output (LAST PHASE)

✅ **NOW you can use canvas** - Only after completing Phases 1-4!

### Step 5a: Create Final Report
`canvas` → Create comprehensive research page:

```
Title: "Research: [Topic]"
Tags: research, [topic keywords]

## TL;DR
[2-3 sentence summary]

## Key Findings
[Organized by theme or importance]

## Sources & Evidence
[Links and citations from stashed artifacts]

## Open Questions
[What remains unclear]
```

---

## Required Tool Order

```
1. mcp_sequentialthinking_sequentialthinking → Plan the research
2. semantic_recall                           → Check existing knowledge
3. native grounding search                   → Fast overview (no tool needed)
4. brave_search (if needed)                  → Fill gaps
5. mcp_fetch_fetch / crawl_url               → READ FULL SOURCES
6. youtube_transcript (if relevant)          → Video content
7. text_summarizer                           → Condense content
8. stash                                     → SAVE ARTIFACTS
9. canvas                                    → FINAL OUTPUT (LAST!)
```

**canvas is ALWAYS LAST. If you haven't used fetch/crawl + stash, you're not ready for canvas.**

---

## Anti-Patterns (DO NOT DO THESE)

❌ **Using canvas early** - Canvas is ONLY for final output after all research
❌ **Skipping fetch/crawl** - Search snippets aren't real research
❌ **Skipping stash** - No artifacts = no follow-up capability
❌ **fetch/crawl AFTER canvas** - That's backwards! Deep dive comes FIRST
❌ **Relying on single source** - Multiple sources required
