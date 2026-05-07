# xAI Native Continuation Implementation Plan

Last updated: 2026-05-03

This plan describes how to wire xAI `store_messages=True`, `previous_response_id`, and structural client-side tool results into Jarvis for real, without replacing Jarvis' existing intelligence, logging, feedback, completion guard, auto-context, Tool RAG, or memory systems.

The goal is narrow: make Grok see the immediate in-flight tool loop as native linked state:

```text
assistant requested Jarvis tool X -> Jarvis executed X -> this is the result of X
```

Jarvis remains the canonical source of truth for everything else.

## Official References

- xAI advanced tool usage and hybrid server/client tools: [https://docs.x.ai/developers/tools/advanced-usage](https://docs.x.ai/developers/tools/advanced-usage)
- xAI tool usage details: [https://docs.x.ai/developers/tools/tool-usage-details](https://docs.x.ai/developers/tools/tool-usage-details)
- xAI streaming and sync tool patterns: [https://docs.x.ai/developers/tools/streaming-and-sync](https://docs.x.ai/developers/tools/streaming-and-sync)
- xAI text / Responses API overview: [https://docs.x.ai/developers/model-capabilities/text/comparison](https://docs.x.ai/developers/model-capabilities/text/comparison)
- xAI prompt caching overview: [https://docs.x.ai/developers/advanced-api-usage/prompt-caching](https://docs.x.ai/developers/advanced-api-usage/prompt-caching)
- xAI prompt caching best practices: [https://docs.x.ai/developers/advanced-api-usage/prompt-caching/best-practices](https://docs.x.ai/developers/advanced-api-usage/prompt-caching/best-practices)
- xAI prompt caching usage and pricing: [https://docs.x.ai/developers/advanced-api-usage/prompt-caching/usage-and-pricing](https://docs.x.ai/developers/advanced-api-usage/prompt-caching/usage-and-pricing)
- xAI WebSocket mode, later optimization candidate: [https://docs.x.ai/developers/advanced-api-usage/websocket-mode](https://docs.x.ai/developers/advanced-api-usage/websocket-mode)

Key doc points to preserve in the implementation:

- Mixed server-side and client-side tools are supported. Server-side tools run automatically on xAI; client-side tools pause execution and must be executed by Jarvis.
- In mixed-tool loops, `max_turns` only caps xAI's internal assistant/server-side tool turns within a single xAI request. After a client-side tool call, Jarvis makes a new follow-up request.
- `store_messages=True` stores the conversation history on xAI servers, including reasoning, server-side tool calls, and tool responses.
- Follow-up calls can use `previous_response_id=response.id` to continue from the stored state.
- With stored continuation, the follow-up request does not need to resend the same system prompt or prior conversation messages in the request body.
- Billing can still include the full conversation history, but prompt caching may reduce cost and latency. Do not treat continuation as "free tokens"; measure `cached_prompt_text_tokens`, total prompt tokens, cost, and latency.
- Stored `response.id` continuation is time-limited. xAI stores server-side conversation state for about 30 days from the original request that created the response id; after that, `previous_response_id` can fail and Jarvis must fall back to locally reconstructed context.

## Current State

The current implementation already has the safe half of the work:

- `LLMProvider.chat_with_tools(...)` accepts `previous_response_id`.
- `XAIProvider` uses the xAI SDK when `XAI_SEARCH=true` and the SDK is available.
- xAI client-side tool definitions use `xai_sdk.chat.tool(...)`.
- xAI tool calls preserve `id`, `tool_call_id`, and `response_id`.
- `_xai_sdk_create_kwargs(...)` only sends `previous_response_id` when `XAI_STORE_MESSAGES=true`.
- `_chat_with_tools_xai_sdk(...)` skips re-adding the routing system prompt only when stored continuation is active.
- `router_v2.py` forwards `previous_response_id` and preserves xAI ids on routes.
- `orchestrator_v2.py` promotes `xai_previous_response_id` only after a Jarvis client-side tool succeeds.
- Duplicate guard and failed tool paths do not advance the xAI continuation handle.

The remaining gap:

- Jarvis still sends most prior tool results back to the router as text through `_build_turn_context(...)`.
- The provider can accept structural `role="tool"` messages, but the main orchestrator does not yet build xAI-native continuation turns from canonical tool state.
- Tool RAG retrieval, provider message construction, and turn-context construction are still coupled around one text string.

## Non-Goals

Do not use xAI stored state as Jarvis' database.

Do not remove or bypass:

- web conversation history
- recent conversation auto-context
- learned knowledge and intelligence injection
- auto memory
- Tool RAG and similarity logging
- feedback records
- completion guard evidence
- tool logs and LLM logs
- `_tool_trace`
- `tools_used`
- `accumulated_data`
- `conversation_context`

Provider-native continuation is a model-behavior optimization, not the source of truth.

## Mental Model

Jarvis should keep three separate layers:

```text
1. Long-term / cross-request Jarvis context
   auto-context, recent history, learned knowledge, auto memory, Tool RAG

2. Canonical in-flight Jarvis state
   conversation_context, tools_used, accumulated_data, tool_trace, usage, completion guard evidence

3. Provider-native continuation state
   previous_response_id, tool_call_id, structural tool_result(...)
```

Only layer 3 should be provider-specific. Layers 1 and 2 must remain provider-agnostic.

## Target Behavior

### Default Off Path

When `XAI_STORE_MESSAGES=false`:

- Behavior remains exactly as it is today.
- The router sends full text turn context through `_build_turn_context(...)`.
- xAI uses the SDK only for native search when enabled, but no stored continuation id is sent.
- OpenAI, Anthropic, Ollama, and xAI OpenAI-compatible fallback remain unchanged.

### Stored Continuation Path

When all are true:

- provider is xAI
- `XAI_SEARCH=true`
- `XAI_STORE_MESSAGES=true`
- previous xAI tool-routing response returned a `response_id`
- Jarvis executed the associated client-side tool successfully
- the tool result has a preserved `tool_call_id`

Then the next router turn should:

- send `previous_response_id=<last successful xAI response id>`
- avoid re-sending the same routing system prompt
- append a structural xAI `tool_result(...)` linked to the preserved tool call id
- avoid sending the full `_build_turn_context(...)` text containing the same tool result
- preserve Tool RAG retrieval, logging, canonical Jarvis state, feedback, and completion guard
- verify the stored response id is inside Jarvis' configured safety window before using it

The simplest target xAI SDK shape is:

```python
chat = xai_client.chat.create(
    model=model,
    tools=current_relevant_tools,
    store_messages=True,
    previous_response_id=last_response_id,
)
chat.append(tool_result(serialized_jarvis_result, tool_call_id=last_tool_call_id))
response = chat.sample()
```

The xAI docs examples often append only `tool_result(...)` on the follow-up call because the prior user request and assistant tool call are hydrated by `previous_response_id`. Start there.

If testing shows Grok needs an extra nudge, add a small optional continuation delta after the tool result:

```text
Continue the original Jarvis request. Use the completed tool result above.
Choose the next required tool only if the original request is not complete;
otherwise answer directly.
```

Gate that delta separately so it can be disabled, and keep `XAI_CONTINUATION_DELTA_MESSAGE=false` as the default. Grok 4.x is expected to do best with only the structural result in most cases; extra text can be added later for specific tricky tool patterns if measurements show it helps.

## System Prompt Handling

The first routing request in a user task should keep the current dynamic system prompt, including date/time, tool policies, memory guidance, and model overrides.

For xAI stored continuation turns:

- do not re-add the same system prompt when `previous_response_id` is active
- rely on xAI to hydrate the original stored system prompt
- accept that the date/time in the stored prompt is from the start of the in-flight request
- do not use stored continuation across separate user requests by default

That last point matters: a web user follow-up minutes or hours later should still use Jarvis' normal recent-history and auto-context path unless a separate cross-request continuation feature is deliberately designed.

## Stored Response Retention

xAI stored continuation ids are not permanent.

Practical rule for Jarvis:

- Treat `response_id` as usable for up to 30 days in principle.
- Use a safer local cutoff, such as 25 days, before attempting `previous_response_id`.
- Check `response_created_at_iso` before every attempted use.
- Check the model used to create the stored response before every attempted use.
- If the stored response id is older than the cutoff, ignore it and use the normal full local context path.
- If the current xAI model differs from the stored response model, ignore the stored response id and use the normal full local context path.
- If xAI returns `previous_response_not_found`, drop the continuation id for that turn and retry through the normal text context path.
- Store enough canonical state locally to reconstruct the turn without xAI stored state.

`tool_call_id` does not need a separate long-term retention policy. It is useful only for matching `tool_result(...)` to the assistant tool call in the stored xAI response. In practice it travels with the associated stored response and becomes unusable when that stored response is no longer available.

Add metadata when storing provider continuation handles:

```python
"provider_continuation": {
    "provider": "xai",
    "response_id": route_response_id,
    "model": route_model,
    "model_alias": configured_model_alias,
    "response_created_at_iso": route_response_created_at,
    "response_expires_at_iso": route_response_created_at + timedelta(days=30),
    "safe_until_iso": route_response_created_at + timedelta(days=25),
    "tool_call_id": route_tool_call_id,
    "tool_name": tool_name,
    "arguments": arguments,
    "result_message": serialized_result_for_provider,
}
```

For strictly in-flight orchestration loops this will usually be minutes old, so the cutoff is mostly a guardrail. It matters more if a future cross-request continuation feature persists xAI ids in web conversation history.

## Token and Cache Expectations

Stored continuation should reduce request payload size and may improve latency because Jarvis stops re-sending the whole prompt and prior tool result text on each route.

It does not mean:

- the full history is free
- prompt tokens disappear from billing
- cache hits are guaranteed

The implementation must log and compare:

- input tokens
- cached prompt text tokens
- output tokens
- reasoning tokens
- `response.cost_usd` when available
- LLM duration
- xAI server-side tool counts
- duplicate guard frequency

Prompt caching docs recommend stable prefixes and conversation affinity. Jarvis now sends `x-grok-conv-id` on the Chat Completions path and as xAI SDK / gRPC metadata by default. If a future xAI Responses API adapter is added, send the same cache-affinity key as `prompt_cache_key` in that request body.

## Architecture Change

The main refactor is to decouple these concepts:

```text
tool retrieval query
provider message payload
human-readable turn context
canonical Jarvis state
```

Today, one `turn_input` text often does all of that.

After the refactor:

- Tool RAG retrieval should still use the original enhanced user request plus relevant routing hints.
- The provider message payload may be structural xAI continuation messages.
- `_build_turn_context(...)` remains the text fallback for non-xAI and for xAI when stored continuation is off or unavailable.
- `conversation_context` remains the canonical source for logs, UI, feedback, completion guard, and fallback synthesis.

## Jarvis Web UI Impact

The Web UI should mostly stay out of provider-native continuation. The stored xAI thread is an in-flight model-routing optimization inside one `orchestrator.process(...)` call, not the Web UI's conversation state.

### `jarvis-web/server/sockets/chat.py`

Keep the current top-level lifecycle:

- WebSocket receives a user message.
- `chat.py` builds recent conversation history via `_get_conversation_context(...)`.
- `chat.py` passes that history into `orchestrator.process(...)`.
- The orchestrator owns any internal xAI continuation between client-side tool calls.
- `chat.py` receives the final canonical Jarvis result and saves/displays it.

Do not have `chat.py` pass saved xAI `previous_response_id` values into a new user request by default. Cross-request provider continuation is a separate future feature because it interacts with fresh time/date, auto-context, learned knowledge, memory injection, and retention expiry.

Live tool cards should not need provider-specific changes:

- `tool:start` still comes from Jarvis before executing a client-side tool.
- `tool:complete` still comes from Jarvis after executing that client-side tool.
- repeated tools are still keyed by `call_index`.
- browser rendering should continue to use canonical `tools_used` and `data`, not xAI stored state.

Optional Web UI/logging improvement:

- Add non-user-facing metadata such as `xai_continuation_mode`, `xai_previous_response_id_present`, and `cached_prompt_text_tokens` to server logs or the existing usage details.
- Do not expose raw `response_id` / `tool_call_id` in normal chat cards unless debugging is explicitly enabled.

### Saved Conversation JSON

Saved conversations should remain provider-neutral and complete:

- keep `tools_used`
- keep `data`
- keep `_tool_trace`
- keep `usage`
- keep `server_side_tools`
- keep `_effective_evidence`
- keep completion guard fields

For strictly in-flight continuation, there is no need to persist xAI response ids into saved web conversation JSON. The orchestrator only needs them while it is still inside the same request.

If cross-request continuation is added later, persist only a small provider metadata block with timestamps and safe expiry:

```json
{
  "_provider_continuation": {
    "provider": "xai",
    "response_id": "...",
    "response_created_at_iso": "...",
    "safe_until_iso": "...",
    "response_expires_at_iso": "..."
  }
}
```

That metadata must be treated as optional. If missing, expired, or rejected by xAI, the normal local-history path should reconstruct context.

### Follow-Up Extraction

`jarvis-web/server/services/followup_extractor.py` should continue to extract compact follow-up data from canonical tool results, not provider continuation state.

That means:

- It should keep reading `data.serpapi_search`, `data.canvas`, `data.stash`, etc.
- It should keep ignoring `_tool_trace`, `usage`, `_effective_evidence`, and server-side bookkeeping.
- If `_provider_continuation` or `provider_continuation` is ever persisted into saved message data, add it to `FOLLOWUP_DATA_SKIP_KEYS`.
- Do not let follow-up extraction rely on xAI stored history. It must work after xAI retention expiry, with other providers, and with local saved conversations.

This separation is important: follow-up extraction is for future user messages and completion evidence; xAI native continuation is for the current in-flight tool loop.

### Completion Guard, Feedback, and Intelligence

These systems should remain attached to Jarvis canonical state:

- Completion Guard should evaluate the final answer against `tools_used`, `data`, `_effective_evidence`, and `server_side_tools`.
- Feedback should record the same final answer, tool list, and saved data as before.
- Intelligence reflections should see the canonical tool trace and results, not xAI's server-side stored thread.
- Log streamers can show continuation metadata as diagnostics, but should not depend on it.

The invariant: if all xAI continuation state vanished, Web UI history, follow-up questions, feedback, completion guard, and intelligence should still work from local saved Jarvis data.

## Proposed Data Shape

Extend each successful `conversation_context` item with provider continuation metadata. Keep it additive.

```python
{
    "tool": tool_name,
    "arguments": arguments,
    "result": result,
    "speech": result.get("speech", ""),
    "meta": {
        "executed_at_iso": "...",
        "freshness": "live_tool_call",
        "xai_response_id": route_response_id,
        "xai_tool_call_id": route_tool_call_id,
    },
    "provider_continuation": {
        "provider": "xai",
        "response_id": route_response_id,
        "model": route_model,
        "model_alias": configured_model_alias,
        "response_created_at_iso": route_response_created_at,
        "response_expires_at_iso": route_response_created_at + timedelta(days=30),
        "safe_until_iso": route_response_created_at + timedelta(days=25),
        "tool_call_id": route_tool_call_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "result_message": serialized_result_for_provider,
    },
}
```

The `provider_continuation` object is optional. Existing consumers should ignore it.

## Result Serialization

Do not pass raw unbounded tool payloads blindly.

Use a provider-facing serializer:

```text
Jarvis tool result
Tool: serpapi_search (call_id: call_123)
Arguments: {"engine": "amazon_product", "asin": "B0FWYF4C6D"}
Status: ok | error
Duration: 11294 ms
Result Meta: result_truncated=false, result_chars_shown=1840, result_chars_total=1840
Result:
<valid structured JSON preview or text preview; never raw-slice JSON. If shortened, include standard truncation marker and result_truncated/result_chars_* metadata>
```

Rules:

- Preserve handles, ids, URLs, ASINs, filenames, stash refs, page ids, and direct product links.
- Preserve error details on failures, but do not advance `previous_response_id` for failed tools until that path is explicitly designed.
- Use existing preview budgets initially.
- Keep the full result in Jarvis state even if the provider-facing result is clipped.
- Add `result_truncated`, `result_chars_shown`, and `result_chars_total` metadata when clipped.

## Implementation Phases

### Phase 0: Observability Before Behavior

Add or verify log fields before changing routing behavior:

- `xai_store_messages_enabled`
- `xai_continuation_enabled`
- `xai_previous_response_id_present`
- `xai_previous_response_id_used`
- `xai_continuation_mode`: `text_fallback`, `stored_structural`, `stored_with_delta`
- `xai_continuation_fallback_reason`
- `xai_response_id`
- `xai_tool_call_id`
- `provider_messages_shape`: counts by role, not full content
- `cached_prompt_text_tokens`
- `xai_cached_prompt_text_tokens`
- `reasoning_tokens`
- `server_side_tools`
- `native_search_remaining`

Files likely involved:

- `lib/llm_logger.py`
- `orchestrator/router_v2.py`
- `orchestrator/orchestrator_v2.py`
- `jarvis-web/server/services/log_streamer.py` if UI log display needs the new fields

### Phase 1: Improve Text Context for All Providers

Low-risk improvement even before native continuation:

- Update `ContextAssembler.build_turn_context(...)` to label results as `Tool result #N`.
- Include arguments in a compact, stable form.
- Include xAI ids when present, but keep this provider-neutral.
- Make repeated tools visibly distinct in text context.

Example:

```text
2. Tool result #2: serpapi_search
   Arguments: {"engine": "amazon_product", "asin": "B0FWYF4C6D"}
   Provider ids: xai_response_id=..., xai_tool_call_id=...
   Result Meta: ok=true, result_truncated=false, ...
   Result: {...}
```

This helps Grok even when `XAI_STORE_MESSAGES=false` and helps all other providers.

### Phase 2: Add a Provider Turn Adapter

Introduce a narrow adapter layer that builds provider-facing route inputs.

Candidate shape:

```python
@dataclass
class ProviderRouteInput:
    tool_retrieval_query: str
    messages: list[dict[str, Any]]
    system_prompt: str | None
    previous_response_id: str | None = None
    mode: str = "text"
```

Responsibilities:

- For default providers, produce the current single user text message.
- For xAI stored continuation, produce structural tool-result messages and no repeated system prompt.
- Keep Tool RAG retrieval query separate from provider messages.

Files likely involved:

- `orchestrator/orchestrator_v2.py`
- `orchestrator/router_v2.py`
- `lib/llm_provider.py`

Important router change:

- `router.route(...)` should accept separate `tool_retrieval_query` and `provider_messages` or accept a `ProviderRouteInput`.
- Tool RAG should rank tools from `tool_retrieval_query`, not from the structural tool result content.
- LLM logging should store both the retrieval query and a safe provider message shape summary.

### Phase 3: Structural xAI Continuation

Add env-gated structural continuation:

```bash
XAI_STORE_MESSAGES=true
XAI_NATIVE_CONTINUATION=true
XAI_CONTINUATION_CONTEXT_MODE=structural
XAI_CONTINUATION_RESULT_MAX_CHARS=6000
XAI_CONTINUATION_DELTA_MESSAGE=false
XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS=25
```

Behavior:

- First turn: current full prompt path.
- Successful Jarvis tool after xAI route: store `response_id` and `tool_call_id`.
- Before using the stored id, check `response_created_at_iso` against `XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS`.
- Before using the stored id, check that the current xAI model matches the stored continuation model.
- Next turn: use `previous_response_id` plus `role="tool"` message.
- Do not include `_build_turn_context(...)` full result text in the provider message.
- Do not re-add the system prompt.
- Continue to include current relevant tools in the xAI SDK `tools` list.
- Return only one client-side tool call to the current executor initially. If xAI returns multiple client-side tool calls, either queue them in a future multi-call executor path or fail closed to the first-call behavior with clear logging.

Provider details:

- `_chat_with_tools_xai_sdk(...)` already supports `role="tool"` via `tool_result(...)`.
- Confirm `tool_result(..., tool_call_id=id)` works with the installed SDK version.
- If the xAI SDK rejects `tool_call_id` or requires a different field name, fail closed to text fallback and log it.

### Phase 4: Fallback and Recovery Rules

Stored continuation must be optional and easy to abandon per turn.

Fallback to text mode when:

- no `response_id`
- no `tool_call_id`
- stored model is missing or differs from the current xAI model
- missing or unparsable `response_created_at_iso`
- response id is older than the configured safe continuation cutoff, default 25 days
- `XAI_STORE_MESSAGES=false`
- `XAI_NATIVE_CONTINUATION=false`
- xAI SDK raises `previous_response_not_found`
- xAI SDK/gRPC fails and OpenAI-compatible fallback is used
- duplicate guard is active and the recovery turn should focus only on existing text context
- the provider is not xAI

On fallback:

- do not lose canonical Jarvis state
- do not clear `conversation_context`
- do not mark the tool as failed unless the tool itself failed
- log `xai_continuation_mode=fallback_text`
- include a safe reason in LLM logs, not in user-facing chat by default

### Phase 5: Trim Redundant Text

Once Phase 3 works:

- For xAI stored structural turns, stop sending full prior tool result text in `_build_turn_context(...)`.
- Send at most a tiny user delta if testing proves it helps.
- Keep the normal full text context for:
  - non-xAI providers
  - xAI with stored continuation disabled
  - xAI fallback
  - duplicate-prevention synthesis
  - completion guard and feedback internals

Do not trim canonical saved data.

### Phase 6: Cross-Request Continuation, Optional Later

Do not start here.

Cross-request xAI continuation is more complex because Jarvis injects fresh auto-context, memory, learned knowledge, and dynamic time/date on each user request.

If implemented later:

- store xAI response ids in saved web conversation metadata
- expire them quickly
- only use them when continuing the same active web thread
- never let stale xAI stored state override Jarvis recent-history and memory injection
- handle 30-day xAI retention limits and `previous_response_not_found`

### Phase 7: Future Provider Parity

OpenAI's Responses API has a similar conceptual continuation path with `previous_response_id` and function call outputs. Treat that as a future adapter, not part of this xAI change.

Long-term provider strategy:

```text
default adapter: text messages
xAI adapter: previous_response_id + structural tool_result(...)
OpenAI Responses adapter: previous_response_id + function_call_output
Anthropic/Ollama: current text context unless native stateful APIs are added
```

## Tests

### Unit Tests

Add tests for:

- `XAI_STORE_MESSAGES=false` keeps current text context path.
- `XAI_NATIVE_CONTINUATION=false` keeps current text context path even if `XAI_STORE_MESSAGES=true`.
- xAI stored continuation with one successful tool creates a provider input with:
  - no system prompt
  - `previous_response_id`
  - one `role="tool"` message
  - correct `tool_call_id`
  - no full `_build_turn_context(...)` result text
- Tool RAG retrieval query remains the original enhanced user request, not the tool result text.
- Missing `tool_call_id` falls back to text context.
- Missing `response_id` falls back to text context.
- Missing or changed stored model falls back to text context.
- Missing or unparsable `response_created_at_iso` falls back to text context.
- Expired or too-old `response_id` falls back to text context.
- `previous_response_not_found` triggers one text-context retry and clears the continuation handle for that turn.
- Duplicate guard does not advance continuation.
- Failed tool execution does not advance continuation.
- Multiple client-side tool calls in one xAI response are logged clearly and handled deterministically.
- Conversation JSON still contains `tools_used`, `data`, `_tool_trace`, usage, and completion guard fields.

### Fake Provider Integration Tests

Use a fake xAI provider that records:

- messages
- system prompt presence
- previous response id
- tool calls returned
- usage metadata

Simulate:

- Q&A only
- one client tool then final answer
- two client tools
- client tool plus server-side native usage metadata
- server-side tool usage and a client-side tool call in the same xAI response
- multiple client-side tool calls in one xAI response
- very large tool result serialization and truncation
- `previous_response_not_found` then one text fallback retry
- SDK failure then fallback
- duplicate attempted call

### Manual Regression Matrix

Run with `XAI_NATIVE_CONTINUATION=false` and then `true`:

- simple Q&A
- single client tool
- multi-tool shopping -> Amazon product -> Canvas
- native xAI search only
- mixed native search plus Jarvis client tool
- image understanding
- video understanding
- tool failure retry
- exact duplicate tool call
- near-duplicate search behavior
- completion guard repair
- feedback submission
- web conversation reload with repeated tool cards

## Metrics to Compare

For each test run, compare:

- total wall-clock time
- per-route LLM duration
- input tokens
- cached prompt text tokens
- output tokens
- reasoning tokens
- xAI server-side tool counts
- Jarvis client-side tool counts
- duplicate guard count
- fallback count
- final answer quality
- completion guard outcome

Expected good signs:

- less request-body bloat on later router turns
- higher cached prompt text tokens
- fewer exact or near-duplicate client tool calls
- fewer 5-minute "thinking after tools" stalls
- no loss of UI cards, logs, feedback, or completion guard evidence

## Rollout Plan

Recommended rollout order:

1. Land Phase 0 and Phase 1 with no behavior change.
2. Land Phase 2 adapter behind tests, still defaulting to text mode.
3. Add Phase 3 behind `XAI_NATIVE_CONTINUATION=false` by default.
4. Test with `grok-4-1-fast-non-reasoning` first.
5. Test with `grok-4.3` on known failing multi-tool prompts.
6. Compare logs from the same prompts with continuation off vs on.
7. Only then consider enabling `XAI_NATIVE_CONTINUATION=true` by default for xAI.

Suggested default config while testing:

```bash
XAI_SEARCH=true
XAI_STORE_MESSAGES=false
XAI_NATIVE_CONTINUATION=false
XAI_SERVER_SIDE_MAX_TOOL_TURNS=8
XAI_SERVER_SIDE_MAX_SEARCHES_PER_REQUEST=6
```

First experimental config:

```bash
XAI_SEARCH=true
XAI_STORE_MESSAGES=true
XAI_NATIVE_CONTINUATION=true
XAI_CONTINUATION_CONTEXT_MODE=structural
XAI_CONTINUATION_DELTA_MESSAGE=false
XAI_PREVIOUS_RESPONSE_MAX_AGE_DAYS=25
XAI_SERVER_SIDE_MAX_TOOL_TURNS=4
XAI_SERVER_SIDE_MAX_SEARCHES_PER_REQUEST=4
```

## Open Questions

- Does the installed `xai-sdk` version accept `tool_result(..., tool_call_id=...)` exactly as expected?
- Does Grok 4.3 perform better with only `tool_result(...)`, or with `tool_result(...)` plus a short continuation delta?
- Does xAI accept `previous_response_id` with a different model in practice? Even if accepted, Jarvis should initially treat model mismatch as a text-fallback condition because reasoning traces, tool behavior, and latency profiles can differ across Grok variants.
- How large should provider-facing tool result payloads be for search-heavy tools?
- Should duplicate-recovery turns forcibly disable xAI server-side tools?
- Can or should `x-grok-conv-id` be set through the SDK/gRPC client for better cache affinity?
- Should xAI continuation ids ever persist across separate web user messages, or remain strictly in-flight?
- Should the safe continuation cutoff remain 25 days, or be shorter for Jarvis web sessions where most benefit is inside one active request?
- Should multiple client-side xAI tool calls be queued/executed in one Jarvis turn, or should the provider continue forcing serial tool calls until the executor supports parallel/multi-call routes?

## Success Criteria

This work is successful when:

- `XAI_STORE_MESSAGES=false` remains behaviorally unchanged.
- Non-xAI providers remain behaviorally unchanged.
- xAI stored continuation can complete multi-tool client-side loops without resending full prior tool result text.
- Jarvis logs, saved web conversations, feedback, completion guard, Tool RAG, and intelligence records remain complete.
- Grok 4.3 shows fewer duplicate or near-duplicate client tool calls on known repro prompts.
- Latency improves or at least becomes more predictable on mixed xAI server-side plus Jarvis client-side tool workflows.
