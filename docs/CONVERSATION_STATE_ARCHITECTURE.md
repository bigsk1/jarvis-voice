# Jarvis Conversation State Architecture

Jarvis keeps conversation state at several scopes. A tool loop remembers the work done during one request. A saved Web conversation supplies selected history to later requests. Recent conversation logs and persistent memory can provide additional context. Optional provider-native continuation helps carry tool results between model calls within an active request.

These mechanisms have different lifetimes. A saved chat is not the same as the model's current input, and a provider response ID is not Jarvis's conversation store.

## State scopes

| Scope | What it contains | Lifetime and selection |
| --- | --- | --- |
| Active request | Tool results, execution trace, duplicate-call guards, usage, and continuation handles | One `Orchestrator.process()` request, including its internal retries |
| Saved Web conversation | User and assistant messages, attachments, and structured result data | Stored by Jarvis; a bounded recent portion is selected for each follow-up |
| DB auto-context | Recent question/answer exchanges, tool names, and outcome metadata | Selected from the active mode's conversation log when enabled and no nonempty history is supplied |
| Persistent memory | Saved facts, resolved preferences, and relevant retrieved memories | Stored in the mode's memory database; selected independently of the recent-message window |
| Provider-native continuation | A provider response reference and the next structured tool result | An optional transport for later model calls in the same active request |

Cloud and local have separate memory databases. Web conversation history is selected by conversation ID; DB auto-context is a recent-log lookup rather than a Web-thread lookup. See [Dual Database System](DUAL_DATABASE_SYSTEM.md) for storage and mode boundaries.

## A request and its tool loop

A normal routed request follows this sequence:

1. The caller supplies the current request and, when available, prior conversation history.
2. The orchestrator assembles history, relevant memory, and other enabled context.
3. The router selects an answer or a tool call from the effective available tools.
4. The executor runs the tool. Its result joins the active request's context.
5. Further router turns can use those results to finish the same request.
6. Jarvis returns the final response and records the applicable conversation and experience data.

For example, “Find the current price and make a chart” can require several model/tool turns while still being one user request. A later “Compare that with yesterday” is a new request and needs history or another source of saved evidence.

`TurnState` owns the in-flight tool context, accumulated results, tool-call trace, duplicate guards, usage counters, and provider continuation handles. A new `process()` call creates a fresh state object. Internal failure retries reuse that request's state and turn budget rather than starting a separate conversation.

Results passed back to the model are bounded projections. Large payloads may be shortened while retaining artifact references, source IDs, and explicit truncation metadata. The full saved artifact and the model-facing preview have different scopes. Tool RAG also selects a relevant tool set rather than sending every installed tool definition on every turn.

Explicit workflow commands have their own pipeline entry point and can return before the normal LLM-routing loop. Durable [background tasks](BACKGROUND-TASKS.md) have a separate job store and delivery lifecycle; they are not held in a provider response ID or only in `TurnState`.

## Saved Web conversations

The Web server reads the selected conversation from `ConversationStore`. It selects recent messages and passes them to the orchestrator through `conversation_history`. The browser displays the chat; server-side saved data supplies follow-up context.

The normal Web history limit is configured in `jarvis-web/config/web_config.json`:

```json
{
  "conversation": {
    "history_limit": 20
  }
}
```

This is a message count, not a token budget. In a simple alternating conversation, 20 messages is approximately ten user/assistant exchanges. The current user message is excluded from prior history because it is already the live request.

Older messages can remain saved and visible when scrolling even after they leave the model's selected history. Raising the history limit allows more prior messages to be considered; it does not guarantee that all of their original text or tool payloads are sent in full.

### Follow-up evidence

For each selected message, context assembly can include:

- User or assistant text and its timestamp.
- Tool names and compact structured results for follow-up actions.
- Attachment context and durable references to uploaded or generated files.
- Timing information when the latest prior assistant timestamp is usable.

The Web follow-up extractor retains useful fields such as Stash references, page IDs, provider/run identifiers, candidates, and bounded source excerpts. Context formatting treats structured tool data as the source of truth and assistant prose as a display summary. Text and attachment excerpts have additional bounds and truncation labels.

This lets a follow-up such as “put those results on Canvas” use saved references without assuming the model remembers the full original tool response. A reference can still become unusable if its underlying file or external resource expires or is deleted; retaining a chat does not retain every referenced artifact indefinitely.

See [Web UI conversation context](JARVIS_WEB_UI.md) and [Stash](STASH_SYSTEM.md) for follow-up and artifact behavior.

## Voice, CLI, and DB auto-context

A voice wake cycle normally starts a new question process. Continuity between those cycles comes from saved context and memory, rather than keeping the previous tool loop alive.

DB auto-context is useful for brief follow-ups such as “What about tomorrow?” after a weather question. It reads recent exchanges from the active mode's `conversations` table, filters them by age, and adds the qualifying questions, responses, tool names, and outcome metadata to the current request.

To enable it, set positive count and age limits in the selected `config/cloud.env` or `config/local.env`:

```bash
AUTO_CONTEXT_ENABLED=true
AUTO_CONTEXT_WINDOW=2
AUTO_CONTEXT_MINUTES=5
```

| Setting | Meaning |
| --- | --- |
| `AUTO_CONTEXT_ENABLED` | Enables the DB-history fallback |
| `AUTO_CONTEXT_WINDOW` | Maximum recent conversation rows considered; each row is a question/answer exchange |
| `AUTO_CONTEXT_MINUTES` | Age cutoff for those exchanges |

The shipped examples disable auto-context in both modes. The cloud example retains a two-exchange, five-minute window; the local example sets both limits to zero. When enabling it in local mode, set usable positive limits as well as the flag.

If all three settings are absent, the implementation falls back to enabled with three exchanges over ten minutes. Those code fallbacks differ from the shipped example configuration; use explicit settings to choose the behavior you want.

### Context selection precedence

For the normal routing path, the orchestrator chooses one recent-history source:

1. A **nonempty** supplied `conversation_history` takes precedence.
2. Otherwise, enabled DB auto-context is attempted.
3. Otherwise, the request proceeds without recent conversation history.

A Web follow-up with supplied history therefore uses its own thread's selected messages. An empty or new Web thread can still fall back to DB auto-context if it is enabled. The fallback is not restricted to CLI or voice, and its recent rows are not filtered to that Web conversation ID.

When no recent row qualifies, auto-context leaves the current request unchanged. It is a bounded history lookup, not a summary of the user's entire conversation archive.

## Persistent memory is separate

Recent history and persistent memory answer different needs. Recent history can resolve “that chart” or “the previous question.” Memory can retain a preference or fact after the recent-history window has passed.

When enabled, automatic memory injection retrieves relevant saved information before routing across CLI, Web, and voice requests. Canonical preferences have their own resolution and injection rules. Tools such as `search_memory` and `semantic_recall` can retrieve saved facts explicitly; conversation-history tools can search prior exchanges when older details are needed.

Disabling `AUTO_CONTEXT_ENABLED` disables the recent-DB-history fallback. It does not disable saved Web history, automatic memory injection, or explicit memory tools. Likewise, a message leaving the Web history window does not delete its saved conversation or convert it into a persistent memory automatically.

Relevant memories are selected and bounded; they do not reproduce every old conversation. [Memory System](MEMORY_SYSTEM.md) explains memory retrieval and configuration. Response style and speech condensation are another separate layer: the shorter speech output is not evidence that the model received no history.

## Provider-side response continuation

Jarvis supports provider-native continuation for eligible OpenAI Responses and xAI SDK tool loops. After the model requests a Jarvis tool, the next model call can send a `previous_response_id` and a structured result for that tool call instead of rebuilding the whole loop as text.

| Provider path | Required configuration and runtime support |
| --- | --- |
| OpenAI Responses | `OPENAI_API_MODE=responses`, `OPENAI_RESPONSES_TOOLS=true`, and `OPENAI_RESPONSES_INFLIGHT_CONTINUATION=true` |
| xAI SDK | `XAI_SEARCH=true`, `XAI_STORE_MESSAGES=true`, `XAI_NATIVE_CONTINUATION=true`, structural continuation mode, and an available search-enabled SDK client |

OpenAI returns the tool result as a `function_call_output` tied to its call ID. The xAI path uses its structural tool-result message. Both retain Jarvis's local result context for fallback.

These settings are opt-in paths with their own storage behavior. In particular, enabling OpenAI in-flight continuation uses `OPENAI_RESPONSES_STORE_CONTINUE` (default `true`) for chainable responses; `OPENAI_RESPONSES_STORE=false` alone does not turn off that continuation storage. Review [OpenAI Provider](OPENAI_PROVIDER.md) and [xAI Provider](XAI_PROVIDER.md) before enabling provider-side storage.

### Scope and fallback

The continuation handles used for routing belong to the active request. A new user message in a saved Web conversation does not resume a persisted provider chain. Jarvis reconstructs that follow-up from its saved local history and compact result data.

Continuation can be bypassed when configuration or request policy disables it, duplicate recovery needs local context, metadata is incomplete, the model differs, or a handle is too old. A recognized provider continuation error allows a bounded retry using the normal text context. That retry is a model-routing fallback; it does not rerun the already completed Jarvis tool merely to reconstruct context.

Other provider paths still use Jarvis's local context assembly. This describes the integrations implemented in Jarvis, rather than claiming that every provider has identical APIs or storage behavior.

## Prompt caching and context size

Prompt caching is separate from conversation history and response continuation. It can reduce repeated-prefix processing or billing when supported by the provider and the request qualifies. It does not make missing older messages visible, preserve a Jarvis tool loop between requests, or remove cached text from the logical context window.

Jarvis keeps stable instructions ahead of changing request context where its prompt assembly allows. Clock updates, tool selection, history, and other request-specific data can change the payload. Cache hits and savings must come from reported usage; they are not guaranteed by the presence of a saved conversation.

A chat's cumulative processed-token total adds usage across model calls and requests. It can be much larger than any single prompt because the same context may be processed repeatedly. The recent-message limit and the model's token context limit are also different bounds: messages can leave the selected history even when the model has token space remaining.

## Practical boundaries

| Question | Current behavior |
| --- | --- |
| Can one request use several tools? | Yes. Its active tool loop carries results forward within that request. |
| Does reopening a saved Web chat replay its entire archive? | No. Follow-ups use selected recent messages and compact evidence. |
| Does a new wake cycle automatically know the last question? | Only when relevant saved history or memory is supplied; DB auto-context must be enabled for its recent-log path. |
| Does a high cumulative token count mean that entire amount is sent next time? | No. Cumulative usage and the next prompt's selected context are different. |
| Does turning off auto-context make Jarvis fully stateless? | No. Web history, memory, tools, and saved artifacts have separate controls and lifetimes. |
| Does provider-native continuation replace the Web conversation store? | No. It is used within an eligible active tool loop. |
| Does a planning MCP tool make a later request resume automatically? | No. An external tool may own state, but Jarvis still needs the appropriate saved context and handles to use it. |

## Implementation map

| Component | Responsibility |
| --- | --- |
| `orchestrator/orchestrator_v2.py` | Select history source, retrieve relevant context, route/execute, and select continuation or fallback |
| `orchestrator/turn_state.py` | Request-local tool-loop bookkeeping and continuation handles |
| `orchestrator/context_assembler.py` | Format supplied history, build DB auto-context, and bound tool-result previews |
| `jarvis-web/server/services/conversation_store.py` | Persist Web conversations and their message data |
| `jarvis-web/server/sockets/chat.py` | Select the recent Web message window and pass history to the orchestrator |
| `jarvis-web/server/services/followup_extractor.py` | Produce compact structured evidence for later Web turns |
| `lib/memory_db.py` | Store memory and conversation-log records for the active mode |
| `lib/openai_responses_adapter.py`, `lib/llm_provider.py` | Provider request conversion and continuation transport |
| `orchestrator/response_formatter.py` | Final response-style and speech formatting |

## Related guides

- [Multi-Turn Orchestration](MULTI_TURN_ORCHESTRATION.md)
- [Auto-Context System](AUTO_CONTEXT_SYSTEM.md)
- [Web UI](JARVIS_WEB_UI.md)
- [Memory System](MEMORY_SYSTEM.md)
- [Dual Database System](DUAL_DATABASE_SYSTEM.md)
- [Tool RAG Strategy](TOOL_RAG_STRATEGY.md)
- [OpenAI Provider](OPENAI_PROVIDER.md)
- [xAI Provider](XAI_PROVIDER.md)
