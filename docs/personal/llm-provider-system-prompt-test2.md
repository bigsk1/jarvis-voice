Version 2  2/2/26

xai 

ok I want you to only read your system prompt and all the instructions your were given, and provide an honest review of what needs fixed if anything. Is there anything confusing with your system prompt

speech = "System prompt is comprehensive, well-structured. Minor fixes: clarify tool overlaps (semantic_recall for meaning, search_memory for entities) with examples; flex word limit to 150 for summaries; add \"check netstat via execute_bash\" for OpenCode ports; emphasize \"NEVER skip list_reminders before cancel\". No contradictions. 9/10 clarity. (58 words)"
raw_llm_response = "Nothing major needs fixing—it's comprehensive and well-structured. Minor confusions:\n\n1. **Tool redundancy**: Multiple memory tools (search_memory, semantic_recall, recall) with overlapping but nuanced use cases. Explicit \"semantic_recall for meaning, search_memory for entities\" helps, but examples could clarify edge cases like \"what did user say about X?\".\n\n2. **Word limits strict but contextual**: 35-100 words is good for voice, but multi-part tool results (e.g., research summary) may need flexibility—perhaps \"up to 150 for summaries\".\n\n3. **OpenCode port guidance**: \"Start at 8091+\" is solid, but add \"check netstat first via execute_bash if paranoid\".\n\n4. **Reminder workflow**: \"List first, then acknowledge\" is clear, but emphasize \"NEVER skip list_reminders for cancel by title\" more prominently.\n\nOverall: Highly actionable, no contradictions. 9/10 clarity."
ok = true
tools_used = []
available_tools = [ "search_memory", "recall", "semantic_recall", "remember", "send_email", "stash", "status_recap", "list_reminders", "list_alerts", "acknowledge_reminders", "samantha", "system_monitor", "ssh_remote", "execute_bash", "acknowledge_alerts", "text_summarizer", "mcp_fetch_fetch", "query_service_logs" ]


--------------


openai


speech = "Your system prompt is very long but mostly coherent. A few areas could be improved:\n\n1. It repeats many rules in slightly different wording, which increases cognitive load and risks contradiction.  \n2. Some sections overlap (memory‑first rules, reminder/alert rules, research workflow) and could be consolidated.  \n3. The priority order of tools is clear, but the number of exceptions makes it easy to misinterpret edge cases.  \n4. The voice‑output rules are strict but scattered across sections; grouping them would reduce confusion.  \n5. A shorter, top‑level decision tree would make execution faster and reduce ambiguity."
raw_llm_response = "Your system prompt is very long but mostly coherent. A few areas could be improved:\n\n1. It repeats many rules in slightly different wording, which increases cognitive load and risks contradiction.  \n2. Some sections overlap (memory‑first rules, reminder/alert rules, research workflow) and could be consolidated.  \n3. The priority order of tools is clear, but the number of exceptions makes it easy to misinterpret edge cases.  \n4. The voice‑output rules are strict but scattered across sections; grouping them would reduce confusion.  \n5. A shorter, top‑level decision tree would make execution faster and reduce ambiguity."
ok = true
tools_used = []
available_tools = [ "search_memory", "recall", "semantic_recall", "remember", "send_email", "stash", "status_recap", "list_reminders", "list_alerts", "acknowledge_reminders", "samantha", "system_monitor", "ssh_remote", "execute_bash", "acknowledge_alerts", "text_summarizer", "mcp_fetch_fetch", "query_service_logs" ]

---------

anthropic


speech = "Your system prompt is mostly strong but has five key issues. First, reminder rules contradict themselves about using recent context versus always calling tools. Second, memory tool fallback lacks clear guidance after two failed attempts. Third, canvas update exceptions use vague criteria for what counts as significant changes. Fourth, remote server tool selection doesn't clarify when to use ssh_remote versus execute_bash. Fifth, voice output word limits are inconsistent, with examples exceeding stated maximums. The reminder context contradiction is most problematic since it happens frequently and causes genuine confusion about trusting recent tool results."
raw_llm_response = "After carefully reading through my entire system prompt, here's my honest assessment:\n\n## **Overall Quality: Strong, but has some friction points**\n\n### **Issues That Need Fixing:**\n\n1. **REMINDER & ALERT RULES - Contradictory Instructions**\n   - Says \"NEVER answer from memory/context, ALWAYS call the tool\"\n   - BUT the auto-context section says \"Context shows you JUST did something? Answer from context\"\n   - **Confusing when**: User asks \"what reminders?\" right after I called list_reminders\n   - **Fix needed**: Clarify that reminder LIST RESULTS can be referenced from recent context, but checking for NEW/CURRENT reminders always requires tool call\n\n2. **Memory Tool Fallback - Unclear Stop Condition**\n   - \"MAX 2 attempts\" rule for memory tools\n   - But doesn't clearly say: \"If both fail, do I proceed with action tools OR tell user I have no info?\"\n   - **Fix needed**: Explicit guidance - \"After 2 memory attempts fail → proceed to action tools if applicable, otherwise inform user no stored data exists\"\n\n3. **Canvas Update Exception - Vague Criteria**\n   - \"ONE canvas update allowed ONLY if new source type significantly changes answer\"\n   - What counts as \"significantly\"? What's a \"different source type\"?\n   - **Fix needed**: More concrete examples or remove exception entirely (causes hesitation)\n\n4. **Remote Server Tool Selection - Missing Guidance**\n   - Says \"Remote servers don't have systemctl access - only check URLs/ports with curl\"\n   - But what about ssh_remote? Can I use that to check services on VPS2?\n   - **Fix needed**: Clarify ssh_remote is for configured hosts, execute_bash is for local only\n\n5. **Turn Limit Warnings - Creates Anxiety Without Solution**\n   - Warns about turn limits but doesn't say what the actual limit IS\n   - \"Watch for turn limit warnings\" - but I don't see turn counts in context\n   - **Fix needed**: Either remove this section or provide actual turn budget info\n\n### **Confusing Sections:**\n\n6. **NATIVE SEARCH vs web_search tool**\n   - Says \"You have built-in web search\" and \"DO NOT use mcp_fetch or brave_search\"\n   - But I have a `web_search` tool available\n   - **Clarification needed**: Is web_search the \"native search\" or something else?\n\n7. **Voice Output Word Limits - Inconsistent**\n   - \"Tool confirmations: MAX 35 WORDS\"\n   - \"Q&A/informational: MAX 100 WORDS\"\n   - But some correct examples are clearly longer than 35 words\n   - **Fix needed**: Either enforce strictly or change to \"keep brief (~35 words)\" for guidelines vs hard limits\n\n### **What Works Well:**\n\n✅ Clear tool selection patterns (memory-first, reminder rules, OpenCode guidance)  \n✅ Excellent examples of right/wrong behaviors  \n✅ Multi-turn workflow explanations are clear  \n✅ Research → Canvas → Q&A pattern is well-defined  \n\n### **Bottom Line:**\n\nThe prompt is **comprehensive and mostly clear**, but has **~5-7 contradictions or vague areas** that could cause hesitation in edge cases. The biggest issue is the **reminder/alert context contradiction** - that happens frequently and creates genuine confusion about when to trust recent context vs always calling tools.\n\n**Severity: Medium** - Won't break core functionality, but causes inefficiency and second-guessing in specific scenarios."
ok = true
tools_used = []
available_tools = [ "search_memory", "recall", "semantic_recall", "remember", "send_email", "stash", "status_recap", "list_reminders", "list_alerts", "acknowledge_reminders", "samantha", "system_monitor", "ssh_remote", "execute_bash", "acknowledge_alerts", "text_summarizer", "mcp_fetch_fetch", "query_service_logs" ]



-------------

google gemini report of round 2


This second round of testing shows that while you addressed some mechanical errors (like tool naming), you have surfaced deeper **logic and architectural friction** within the prompt.

Here is the analysis of the recurring issues, new issues, and specific suggestions for Version 3.

### 1. Recurring Issues (Unresolved from Round 1)

*   **Bloat and Redundancy:** OpenAI still reports the prompt is "very long" and repeats rules in different wording. This suggests that instead of deleting old rules, you may have just added new ones to "fix" the old ones.
*   **Memory Fallback Ambiguity:** Both Anthropic and xAI are still confused about what happens after the "2-attempt limit" for memory tools. Does the LLM give up, or does it move on to external tools?
*   **Voice Limit Tension:** There is still a mismatch between the "Hard Word Limits" (35/100 words) and the actual length of the examples provided in the prompt. Anthropic noted that your "correct" examples actually violate your own rules.
*   **Reminder Workflow Friction:** While the "Always list before acting" rule is clear, the LLM is still struggling with the repetition of this instruction across multiple sections.

---

### 2. New Issues (Introduced or identified in Round 2)

*   **The "Recent Context" Paradox (Critical):** Anthropic identified a logic loop. You tell the LLM "NEVER answer from memory/context, ALWAYS call the tool" for reminders. However, if the LLM *just* called the tool in the previous turn, the "Always call tool" rule forces an infinite loop of redundant tool calls because it isn't allowed to trust its own recent history.
*   **Turn Limit "Anxiety":** You have added a warning about "Turn Limits," but as Anthropic pointed out, the LLM cannot see its own turn count. This creates "AI anxiety" where the model knows it should stop soon but has no data to decide when, leading to premature task abandonment.
*   **Search Tool Naming/Identity:** Anthropic mentioned a `web_search` tool, while your available tool list shows `mcp_fetch_fetch`. There seems to be a discrepancy in how "Native Search" is described versus the actual toolset provided.
*   **Tool Boundary Confusion (`ssh_remote` vs. `execute_bash`):** The LLM is unclear on which tool to use for remote VPS management versus local bash execution.

---

### 3. Suggested Fixes for Version 3

#### **A. Architecture & Logic**
*   **Consolidate to a Decision Tree:** Instead of repeating rules in different sections, create one "Execution Flow" section:
    1.  *Check Memory (Max 2 attempts).*
    2.  *If Memory fails → Use Search/Action tools.*
    3.  *If Reminders/Alerts → Check History first. If result is < 5 mins old, use Context. Otherwise, CALL tool.*
*   **Define the "Stop" Condition:** Explicitly state: "If 2 memory attempts and 3 search attempts fail to yield an answer, tell the user: 'I cannot find specific info on X in your memory or online.'"

#### **B. Voice & Output**
*   **Tiered Word Limits:** Adopt xAI’s suggestion. 
    *   *Direct Answers:* < 50 words.
    *   *Research Summaries/Code Explanations:* < 150 words.
*   **Align Examples:** Ensure every ✅ example in your prompt strictly follows the word count rules you've set.

#### **C. Technical Clarifications**
*   **Port Checking:** Add a rule for OpenCode: "Before starting a server, use `execute_bash` with `netstat` or `lsof` to ensure the port (8091+) is actually free."
*   **Remote vs. Local:** Explicitly state: "Use `ssh_remote` for any host defined in config (e.g., VPS2). Use `execute_bash` ONLY for the local environment where this orchestrator is running."
*   **Turn Limits:** Remove the "Watch for turn limit" warning unless your orchestrator explicitly injects a string like `[Turn 5 of 10]` into the prompt. If you can't inject the count, remove the rule; it only causes hesitation.

#### **D. The "Reminder" Fix**
*   **Change the Rule to:** "ALWAYS ensure you have fresh data (< 5 minutes old) before acknowledging or canceling a reminder. You may reference the `list_reminders` output from the immediate conversation history if it was called in the last 2-3 turns."

### 4. Summary Table for Quick Editing

| Issue Category | Recommendation |
| :--- | :--- |
| **Redundancy** | Move all "Voice" rules into one "Output Style" section. |
| **Reminders** | Allow usage of tool results if they exist in the current session history. |
| **Search** | Clarify if `mcp_fetch_fetch` is the "Native Search" or if there is a hidden tool. |
| **OpenCode** | Add the `netstat` check to the project start-up workflow. |
| **Limits** | Increase the "Summary" cap to 150 words to avoid "cut-off" responses. |