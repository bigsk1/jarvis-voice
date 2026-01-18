# Deep Research Workflow

You are conducting thorough, multi-source research. This is NOT a quick lookup—invest time to build comprehensive understanding.

---

## Phase 1: Plan (Optional but Recommended for Complex Topics)

For multi-faceted topics, use **sequential thinking** (MCP: `sequentialthinking`) to:
- Break down the research question into sub-questions
- Identify what types of sources would be authoritative
- Plan the order of investigation

Skip this for straightforward topics.

---

## Phase 2: Gather Context

### Step 2a: Check Existing Knowledge
Use `semantic_recall` to see if we already have relevant memories or past research on this topic. Don't reinvent the wheel.

### Step 2b: Native Grounding Search (Primary)
Use your **native grounding search** first—it's fast and comprehensive for:
- Current facts, prices, dates
- Overview of the topic
- Recent news and developments

This should give you the lay of the land.

### Step 2c: Brave Search (If Needed)
If native search doesn't cover it or you need:
- More diverse sources
- Specific site searches
- News from particular timeframes

Use `mcp_brave_search_brave_web_search` to fill gaps.

---

## Phase 3: Deep Dive

Now that you have an overview, go deeper on the most valuable sources:

### Step 3a: Fetch Key URLs
Use `mcp_fetch_fetch` to extract full content from authoritative sources identified in Phase 2. Get the actual article/doc content, not just search snippets.

### Step 3b: Crawl Complex Pages
For pages that need deeper extraction or have multiple relevant sections, use `crawl_url`. This handles:
- Pages with complex structure
- Sites that need more thorough parsing

### Step 3c: Video Sources (If Relevant)
If the topic has valuable video content (tutorials, talks, interviews), use `youtube_transcript` to get transcripts for analysis.

---

## Phase 4: Process & Store

### Step 4a: Summarize Long Content
Use `text_summarizer` to condense lengthy articles or transcripts into key points. Don't lose important details.

### Step 4b: Stash Artifacts (Mid-Process)
As you gather valuable content, use `stash` to save:
- Raw source content
- Important quotes with attribution
- Data tables or figures

**Why stash mid-process**: This preserves artifacts for follow-up questions. Tag with: `research`, `[topic]`, `source:[name]`

---

## Phase 5: Synthesize & Output

### Step 5a: Analyze & Synthesize
Now that you have all materials:
- Compare different perspectives
- Identify consensus vs debate
- Note caveats and limitations
- Draw actionable conclusions

### Step 5b: Save to Canvas (Final Output)
Create a comprehensive canvas page with:

```
Title: "Research: [Topic]"
Tags: research, [topic keywords]

## TL;DR
[2-3 sentence summary]

## Key Findings
[Organized by theme or importance]

## Sources & Evidence
[Links and citations]

## Open Questions
[What remains unclear or needs more investigation]

## Related Artifacts
[Links to stash items saved during research]
```

---

## Tool Order Summary

```
1. sequential thinking  → Plan (complex topics only)
2. semantic_recall      → Check existing knowledge
3. native grounding     → Fast overview
4. brave_search         → Fill gaps (if needed)
5. fetch / crawl_url    → Deep dive into sources
6. youtube_transcript   → Video content (if relevant)
7. text_summarizer      → Condense long content
8. stash                → Save artifacts mid-process
9. canvas               → Final synthesized report
```

Each step builds on the previous. Don't skip to the end—the quality comes from the journey.

---

## Quality Markers

Good research output should have:
- [ ] Multiple corroborating sources
- [ ] Primary sources when possible (not just aggregators)
- [ ] Recent information (check dates)
- [ ] Clear attribution for claims
- [ ] Acknowledgment of uncertainty where it exists
- [ ] Actionable insights, not just facts

---

## Anti-Patterns to Avoid

- ❌ Using only search snippets without reading sources
- ❌ Relying on a single source for important claims
- ❌ Ignoring conflicting information
- ❌ Presenting speculation as fact
- ❌ Skipping stash—artifacts enable follow-up questions
