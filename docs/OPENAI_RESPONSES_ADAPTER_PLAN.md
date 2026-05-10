# OpenAI Responses Adapter Plan

Last updated: 2026-05-10

Status: Implemented behind config gates in Jarvis v2.50.0. This document remains the design record and rollout checklist; the live provider reference is [OPENAI_PROVIDER.md](OPENAI_PROVIDER.md).

This plan is a working design note for evaluating OpenAI's Responses API in Jarvis without destabilizing the existing xAI provider path.

The conservative goal is narrow:

```text
Use OpenAI Responses for OpenAI tool-routing experiments,
optionally use previous_response_id only during one in-flight Jarvis tool loop,
and keep Jarvis as the canonical state, memory, tool, logging, and follow-up system.
```

This is not a plan to replace Jarvis memory with OpenAI stored conversations. It is also not a plan to refactor xAI continuation into a shared abstraction before the OpenAI path proves itself.

## Official References

- OpenAI migration guide: https://developers.openai.com/api/docs/guides/migrate-to-responses
- OpenAI function calling: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI using tools: https://developers.openai.com/api/docs/guides/tools
- OpenAI web search tool: https://developers.openai.com/api/docs/guides/tools-web-search
- OpenAI code interpreter tool: https://developers.openai.com/api/docs/guides/tools-code-interpreter
- OpenAI file search tool: https://developers.openai.com/api/docs/guides/tools-file-search
- OpenAI prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI image generation API choices: https://developers.openai.com/api/docs/guides/image-generation
- OpenAI text to speech: https://developers.openai.com/api/docs/guides/text-to-speech

Key doc points to preserve in Jarvis:

- Responses uses `input` instead of Chat Completions `messages`, though message-shaped input can be used for simple migrations.
- Responses returns typed `output` items. Text may be read through `response.output_text`; function calls are output items with `type="function_call"`.
- Function call results are sent back as `{"type": "function_call_output", "call_id": "...", "output": "..."}`.
- Built-in server-side tools are a first-class Responses feature. Docs show tools such as `web_search`, `file_search`, and `code_interpreter` in `client.responses.create(...)`.
- Built-in tool usage also appears as typed output items, such as `web_search_call`, `file_search_call`, and `code_interpreter_call`. ( no need for file search tool in jarvis) 
- Model support varies. Check the selected model's tool-support table instead of assuming all OpenAI models support the same built-in tools.
- Responses can chain with `previous_response_id`, but that is provider-native state. Jarvis must still be able to rebuild the turn from local canonical state.
- Prompt caching rewards stable prefix structure. Static system/tool content should stay before dynamic user/runtime context.

## Current Jarvis Boundaries

Jarvis is the adapter and orchestrator. Providers are execution backends, not the source of truth.

Keep these layers separate:

```text
1. Cross-request Jarvis context
   Web UI conversation history, auto-context, memory, intelligence, follow-up extraction

2. Canonical in-flight Jarvis state
   conversation_context, tools_used, accumulated_data, tool trace, logs, completion guard evidence

3. Provider-native continuation state
   previous_response_id, provider tool call id, provider-specific structural tool result
```

Only layer 3 should be provider-specific.

OpenAI Responses should not change how Web UI follow-ups work. Web follow-up logic already passes prior local data back into Jarvis. After one user request finishes, Jarvis should discard OpenAI `previous_response_id` unless a separate cross-request continuation feature is deliberately designed later.

## Lessons From xAI Continuation Work

The xAI continuation work exposed several Jarvis-specific constraints that also apply to OpenAI Responses.

### Separate the Routing Inputs

Do not let one text string serve every purpose.

The xAI work added `ProviderRouteInput` so Jarvis can keep these separate:

```text
tool retrieval query
provider message payload
human-readable fallback turn context
canonical Jarvis state
```

OpenAI Responses should reuse that separation. Tool RAG should rank tools from the original enhanced user request plus compact routing hints. It should not rank tools from a structural `function_call_output` body, because that body is a provider continuation artifact, not the user's next routing intent.

### Keep Structural Provider Messages Out of Fallback Paths

The xAI plan had to guard against sending orphan structural `role="tool"` messages into an OpenAI-compatible Chat Completions fallback. The OpenAI version has the same risk in reverse.

If OpenAI Responses continuation fails, Jarvis should retry once using normal local text context. It should not feed `function_call_output` items into Chat Completions or any provider path that does not understand Responses item types.

### Store Continuation Only After Successful Tool Execution

The continuation handle is not valid just because a provider asked for a tool.

Jarvis should only promote OpenAI continuation metadata after:

- the provider returned a `response_id`
- the provider returned a function `call_id`
- Jarvis executed the client-side tool
- the tool result is successful enough for the next model turn

Duplicate guard stops, failed tools, canceled tools, and provider retries should not advance the continuation handle.

### Serialize Tool Results Deliberately

The xAI implementation needed a bounded provider-facing serializer instead of dumping raw tool payloads into provider state.

OpenAI should use the same lesson:

- keep full raw results in Jarvis canonical state
- send a bounded structured result to the provider
- preserve ids, URLs, filenames, stash refs, product ids, page ids, and other handles
- avoid raw-slicing JSON into invalid JSON
- include truncation metadata when provider-facing output is clipped

### Web UI Stays Provider-Neutral

The Web UI should not become aware of OpenAI `previous_response_id`.

Live tool cards should still come from Jarvis events. Saved conversation JSON should remain complete through `tools_used`, `data`, `_tool_trace`, `usage`, `server_side_tools`, and completion guard fields.

If a future experiment ever persists provider continuation metadata, follow-up extraction should ignore it. Follow-ups must continue to work after provider retention expires, with local models, and with other cloud providers.

### Observability Before Behavior

The xAI plan added diagnostics before changing routing behavior. OpenAI should follow that pattern.

Useful early diagnostics:

- OpenAI API mode: `chat` or `responses`
- whether Responses tools are enabled
- whether `previous_response_id` was present
- whether `previous_response_id` was used
- continuation mode: `text_fallback`, `responses_structural`, `responses_with_delta`
- fallback reason
- provider message shape, by item type/count, not full content
- response id and call id presence, with raw ids hidden outside debug logs
- cached input tokens, output tokens, reasoning tokens if present
- duplicate guard count and fallback count

### Provider SDKs Can Diverge

Do not assume xAI and OpenAI SDK behavior will stay aligned just because both expose tool and continuation concepts.

Keep provider-specific adapters for:

- tool definition shape
- response output item parsing
- server-side tool call counting
- continuation item shape
- retryable error detection
- request transport assumptions

Shared code should stay limited to stable Jarvis-owned concepts such as `server_side_tools`, usage aggregation, local text fallback, and provider-facing tool-result serialization.

## Non-Goals

Do not generalize the xAI continuation implementation yet.

Do not change the working xAI flow as part of the first OpenAI Responses experiment:

- Do not rename xAI continuation variables.
- Do not move xAI continuation logic into a provider-neutral framework.
- Do not alter xAI `XAI_STORE_MESSAGES`, `XAI_NATIVE_CONTINUATION`, SDK fallback, cache affinity, or server-side tool behavior.
- Do not require xAI tests to change for the OpenAI adapter to land.

Do not use `previous_response_id` for normal Q&A/direct-answer turns.

This does not mean every Q&A/direct-answer turn must use Chat Completions. In Jarvis, the router often calls `OpenAIProvider.chat_with_tools(...)` with a non-empty ghost-tool set before the model decides whether to answer directly or call a tool. When `OPENAI_API_MODE=responses` and `OPENAI_RESPONSES_TOOLS=true`, those tool-capable routing calls may use `/v1/responses` even if the model returns final text. The non-goal is provider-native continuation for Q&A, not Responses transport for a tool-capable routing call.

Do not persist OpenAI response ids across saved Web UI follow-up turns.

Do not replace Jarvis systems:

- Tool RAG
- memory and intelligence
- auto-context
- Web UI conversation history
- completion guard
- feedback
- `_tool_trace`
- usage and cost logging
- tool execution logs

Do not migrate these APIs in the first pass:

- STT: keep `/audio/transcriptions`
- TTS: keep `/audio/speech` and OpenAI-compatible local TTS servers
- image generation/editing: keep `/images/generations` and `/images/edits`
- Sora video: keep the video SDK API
- embeddings: keep the embeddings API
- tiny status summaries: keep the current short OpenAI-compatible Chat Completions path unless a later cleanup pass says otherwise

## Proposed Scope

Start with OpenAI tool-capable routing only.

The first implementation should live inside `OpenAIProvider` as an adapter-local path:

```text
OpenAIProvider.chat_with_tools(...)
  -> chat completions path, current default
  -> responses path, behind OpenAI-specific config
```

Suggested flags:

```env
OPENAI_API_MODE=chat                  # chat | responses
OPENAI_RESPONSES_TOOLS=false          # first enablement gate
OPENAI_RESPONSES_INFLIGHT_CONTINUATION=false
OPENAI_RESPONSES_SERVER_SIDE_TOOLS=false
OPENAI_RESPONSES_WEB_SEARCH=false
OPENAI_RESPONSES_FILE_SEARCH=false
OPENAI_RESPONSES_CODE_INTERPRETER=false
OPENAI_RESPONSES_SERVER_SIDE_MAX_TOOL_CALLS=0
OPENAI_RESPONSES_PARALLEL_TOOL_CALLS=false
```

If Responses storage defaults are not desired, the adapter should set `store=false` when continuation is disabled. If in-flight continuation is enabled, storage behavior must be explicit and documented.

## Transport and Fallback Assumptions

xAI has an OpenAI-compatible fallback because the xAI SDK path uses gRPC and Jarvis has seen transient DNS/gRPC resolver failures there.

OpenAI Responses should not start with the same fallback model.

The installed OpenAI Python SDK uses an HTTP client wrapper for the OpenAI client, and the Responses API endpoint is `/v1/responses`. Treat Responses failures as normal HTTP/API failures unless proven otherwise:

- retry only normal transient HTTP conditions according to existing SDK behavior or a small Jarvis wrapper
- do not fallback from Responses to Chat Completions with structural Responses payloads
- do not use Chat Completions as an automatic fallback for OpenAI server-side tools
- keep Chat Completions as the explicit `OPENAI_API_MODE=chat` default/path, not as a hidden transport fallback

If OpenAI Responses is unavailable for a model or request shape, fail closed to the existing local text/context path and let config choose Chat Completions on the next request.

OpenAI has also had Chat Completions search-preview model support, but Jarvis should target the Responses tool surface for this plan. Responses is where the general built-in tool set lives across web search, file search, Code Interpreter, and future OpenAI tool types.

## In-Flight Lifecycle

### 1. First router turn in a user request

Use the normal Jarvis path:

- full dynamic routing system prompt
- Tool RAG-selected Jarvis tools
- memory and intelligence context
- Web UI or CLI user message context
- no `previous_response_id`

If OpenAI Responses is enabled for tool-capable routing and the provider receives a non-empty tool list, the adapter calls `client.responses.create(...)`. A direct final-text response from that call is still a normal Jarvis Q&A/direct-answer result; it does not imply any provider continuation state should be reused.

If the model returns final text, Jarvis answers and discards the provider response id.

If the model returns a Jarvis tool call, the adapter returns the existing Jarvis tuple shape:

```python
(None, tool_call, usage_info, thinking)
```

The `tool_call` should include:

```python
{
    "name": "...",
    "arguments": {...},
    "id": "...",              # provider function_call item id when available
    "tool_call_id": "...",    # same as call_id for Jarvis compatibility
    "response_id": "resp_...",
}
```

### 2. Jarvis executes the tool

No provider owns this step.

Jarvis executes the selected tool, logs it, appends canonical `conversation_context`, updates `_tool_trace`, tracks usage, and keeps completion guard evidence exactly as it does today.

Only after a successful Jarvis tool execution may an OpenAI continuation handle be considered usable.

The provider-facing result should come from the same bounded serialization idea used for xAI, not from raw `result` dumping. The full result remains in Jarvis state.

### 3. Next router turn inside the same user request

If all conditions are true:

- provider is OpenAI
- Responses tool path is enabled
- in-flight continuation is enabled
- the previous OpenAI response returned `response_id`
- the previous OpenAI function call returned `call_id`
- Jarvis executed that tool successfully
- this is still the same in-flight user request

Then the next OpenAI Responses call may send:

```python
client.responses.create(
    model=model,
    previous_response_id=last_response_id,
    input=[
        {
            "type": "function_call_output",
            "call_id": last_call_id,
            "output": serialized_jarvis_tool_result,
        }
    ],
    tools=current_relevant_tools,
)
```

The provider-facing input should not include a full duplicate text copy of the same tool result when the structural `function_call_output` is being used.

A small delta instruction can be tested only if needed:

```text
Continue the original Jarvis request. Use the completed tool result above.
Choose the next required tool only if the original request is not complete;
otherwise answer directly.
```

Keep this delta behind a separate flag because extra text can change model behavior and reduce the clarity of the structural handoff.

### 4. End of the user request

When the request finishes with a final answer, a hard error, a duplicate guard stop, or completion guard handoff:

- clear OpenAI in-flight continuation state
- do not pass OpenAI `previous_response_id` to the next user message
- do not store OpenAI response ids in Web UI follow-up payloads
- rely on Jarvis saved conversation history, follow-up extraction, memory, and context assembly for later turns

## Fallback and Recovery Rules

OpenAI Responses continuation must be optional and easy to abandon per turn.

Use normal local text context when:

- Responses mode is disabled
- Responses tool mode is disabled
- in-flight continuation is disabled
- there is no `response_id`
- there is no function `call_id`
- the tool did not complete successfully
- duplicate guard is active
- the provider rejects `previous_response_id`
- the provider rejects `function_call_output`
- the provider falls back to Chat Completions
- the model used for the stored response does not match the current OpenAI model
- timestamps are missing, stale, or unparsable
- the request is a later Web UI follow-up rather than the same in-flight user request

On fallback:

- do not clear `conversation_context`
- do not lose tool results
- do not mark the tool as failed unless the tool itself failed
- log a safe fallback reason
- retry the provider turn at most once with text context for continuation rejection
- clear the OpenAI in-flight continuation handle for that turn

## Provider-Facing Result Serialization

OpenAI `function_call_output.output` should be a compact string built from canonical Jarvis state.

Suggested structure:

```text
Jarvis tool result
Tool: serpapi_search
Call ID: call_123
Arguments: {"engine": "amazon_product", "asin": "B0FWYF4C6D"}
Status: ok
Duration: 11294 ms
Result Meta: result_truncated=false, result_chars_shown=1840, result_chars_total=1840
Result:
<valid structured JSON preview or text preview>
```

Rules:

- Preserve handles, ids, URLs, ASINs, filenames, stash refs, image ids, video ids, and page ids.
- Use a stable character budget such as `OPENAI_RESPONSES_RESULT_MAX_CHARS`.
- Keep full raw results in `conversation_context`, `accumulated_data`, saved Web UI data, feedback, and completion guard evidence.
- If clipped, include `result_truncated`, `result_chars_shown`, and `result_chars_total`.

## Tool Schema Work

Current Jarvis OpenAI tools are Chat Completions shaped:

```python
{
    "type": "function",
    "function": {
        "name": name,
        "description": description,
        "parameters": parameters,
    },
}
```

Responses should get an adapter conversion layer, not a repo-wide schema replacement.

Target adapter shape:

```python
{
    "type": "function",
    "name": name,
    "description": description,
    "parameters": parameters,
}
```

Keep the existing schema sanitizer. Add tests that prove the same `ToolSchema` can produce:

- current Chat Completions format
- Responses format
- sanitized parameters in both paths

## Multiple Tool Calls

Jarvis currently executes one client-side tool call at a time in the router loop.

OpenAI Responses can return multiple function calls. The first OpenAI implementation should be explicit about behavior:

- Prefer disabling parallel tool calls if the selected model/API supports that parameter.
- Otherwise, pick one tool deterministically and log that multiple calls were returned.
- Do not execute multiple Jarvis tools in parallel until the orchestrator is deliberately designed for that.

This mirrors the safe xAI posture and avoids surprising multi-tool side effects.

## OpenAI Server-Side Tools

Do not enable OpenAI server-side tools by default, but plan them as a serious Responses feature lane.

Jarvis already has generic server-side-tool plumbing from xAI and Anthropic:

- `usage_info["server_side_tools"]` is accumulated across router turns
- `LLMLogger` writes a dedicated server-side-tools log
- Web UI displays a toast from top-level `server_side_tools` or `usage.server_side_tools`
- completion guard treats provider-native tools as evidence
- feedback and intelligence reflection normalize provider-native tools as metadata, not Jarvis tool choices

OpenAI should tap that existing generic path, with OpenAI-specific extraction in the Responses adapter.

Suggested normalized labels:

```python
{
    "SERVER_SIDE_TOOL_WEB_SEARCH": 2,
    "SERVER_SIDE_TOOL_FILE_SEARCH": 1,
    "SERVER_SIDE_TOOL_CODE_INTERPRETER": 1,
}
```

The existing UI and reflection code will turn these into readable labels such as `Web Search`, `File Search`, and `Code Interpreter`.

OpenAI-specific tool config should remain separate from xAI/Anthropic config:

```env
OPENAI_RESPONSES_SERVER_SIDE_TOOLS=false
OPENAI_RESPONSES_WEB_SEARCH=false
OPENAI_RESPONSES_FILE_SEARCH=false
OPENAI_RESPONSES_CODE_INTERPRETER=false
OPENAI_RESPONSES_SERVER_SIDE_MAX_TOOL_CALLS=0
OPENAI_RESPONSES_WEB_SEARCH_ALLOWED_DOMAINS=
OPENAI_RESPONSES_WEB_SEARCH_BLOCKED_DOMAINS=
OPENAI_RESPONSES_FILE_SEARCH_VECTOR_STORE_IDS=
OPENAI_RESPONSES_CODE_INTERPRETER_MEMORY_LIMIT=1g
```

Initial scope should be web search only. File search needs vector store selection, and Code Interpreter needs container policy, file handling, cost limits, and generated-file handling.

### Server-Side Tool Budgeting

Jarvis already has a per-request native-search budget shape for xAI. OpenAI should reuse the concept, not the xAI env names.

Desired behavior:

- The orchestrator keeps using a provider-neutral `disable_server_side_tools` decision.
- When a client-side search hint is active, OpenAI server-side tools are disabled for that provider turn.
- When the per-request OpenAI server-side budget is exhausted, OpenAI server-side tools are disabled.
- The OpenAI provider should read OpenAI-specific disable/budget config or accept provider-local options when the interface grows.

Do not route OpenAI disable logic through `XAI_DISABLE_SERVER_SIDE_TOOLS` or `XAI_SERVER_SIDE_MAX_TOOL_TURNS`. Those are xAI-specific implementation details.

### System Prompt and Judges

The router system prompt already has provider-native search/tool notes for xAI and Anthropic. Add an OpenAI branch only when:

- provider is OpenAI
- Responses mode is active
- OpenAI server-side tools are enabled
- the selected model supports the enabled tool types

The note should be explicit that OpenAI server-side tools are provider-native evidence paths. It should also tell the model when to prefer Jarvis client-side tools, especially for local files, stash refs, actions, account-specific operations, memory, and workflows.

Feedback, intelligence, and completion guard should not need a new philosophy. They already consume `server_side_tools`; they may only need label updates so OpenAI native search/code/file usage is recognized in examples and prompt wording.

### Response Parsing

The Responses adapter should count server-side calls by scanning typed output items:

- `web_search_call` -> `SERVER_SIDE_TOOL_WEB_SEARCH`
- `file_search_call` -> `SERVER_SIDE_TOOL_FILE_SEARCH`
- `code_interpreter_call` -> `SERVER_SIDE_TOOL_CODE_INTERPRETER`

Do not assume every built-in tool reports usage in the same field. Parse output items first, then merge any official usage fields if available.

For web search, consider `include=["web_search_call.action.sources"]` only when Jarvis needs source-level audit details. For file search, `include=["file_search_call.results"]` may be useful but can bloat logs and should be gated.

## Prompt Caching Expectations

OpenAI prompt caching is automatic for eligible prompts, but Jarvis should still structure prompts deliberately:

- stable routing instructions first
- stable tool definitions before dynamic runtime context
- dynamic user/task/context data last
- avoid needless churn in tool descriptions
- measure cached token counts rather than assuming savings

The OpenAI Responses adapter should extract cached token details from usage when present and pass them into Jarvis cost/logging metadata.

Useful metrics:

- input tokens
- cached input tokens
- output tokens
- reasoning tokens if present
- request duration
- number of router turns
- duplicate guard hits
- whether structural continuation was used

## Implementation Sequence

### Phase 0: Design only

Keep this document as the working plan while decisions are still being ironed out.

### Phase 0.5: Diagnostics before behavior

Add logging and shape summaries before changing provider behavior.

Constraints:

- log provider message item counts/types, not full structural payloads
- log fallback reasons in LLM logs, not normal user-facing chat
- hide raw provider ids unless debug logging is enabled
- keep xAI diagnostics unchanged

### Phase 1: Adapter-local Responses path

Add an OpenAI Responses path inside `OpenAIProvider`.

Constraints:

- default remains Chat Completions
- no xAI files changed unless tests reveal an unrelated break
- no `previous_response_id` yet
- no OpenAI server-side tools yet
- no Web UI follow-up persistence
- no structural `function_call_output` fallback into Chat Completions

### Phase 2: Tool schema and parser tests

Add unit tests for:

- Chat tool schema still unchanged
- Responses tool schema conversion
- typed text output parsing
- single `function_call` parsing
- multiple `function_call` handling
- usage extraction, including cached tokens when present

### Phase 3: One-tool end-to-end trial

Enable Responses for a single OpenAI tool-routing call without continuation.

Goal:

```text
Jarvis asks OpenAI -> OpenAI calls one Jarvis tool -> Jarvis executes it -> Jarvis continues through existing local text context
```

This proves the adapter without touching in-flight continuation.

### Phase 4: OpenAI server-side web search

Enable OpenAI `web_search` behind OpenAI-specific config after the base Responses adapter works.

Constraints:

- default remains off
- no file search or code interpreter yet
- count `web_search_call` output items into `SERVER_SIDE_TOOL_WEB_SEARCH`
- pass through top-level `server_side_tools` so the existing Web UI toast works
- make feedback/intelligence/completion guard aware through the existing `server_side_tools` metadata path
- apply provider-native tool disable/budget logic without xAI env variables

### Phase 5: OpenAI-only in-flight continuation

Add OpenAI-specific continuation helpers, parallel to the xAI helpers, not replacing them.

Use names like:

- `openai_responses_continuation_enabled`
- `openai_previous_response_id`
- `_build_openai_responses_route_input(...)`
- `_build_openai_provider_continuation(...)`

Avoid provider-neutral renaming until both implementations are stable.

The OpenAI route input should reuse the existing `ProviderRouteInput` split:

- Tool RAG retrieval query: original enhanced user request plus compact tool hints
- provider messages/input: Responses structural `function_call_output`
- system prompt: omitted only when `previous_response_id` safely hydrates the original provider state
- fallback: normal local text turn context

### Phase 6: Optional file search and code interpreter

Consider these only after web search telemetry is boring.

File search needs:

- vector store id config
- include/result-size policy
- completion guard evidence mapping
- privacy handling for uploaded files

Code Interpreter needs:

- container mode policy
- memory limit config
- generated-file download/storage policy
- timeout and cost caps
- clear distinction from Jarvis `execute_bash` and `opencode`

### Phase 7: Measurement

Compare Chat Completions vs Responses on:

- successful route rate
- malformed tool-call rate
- server-side tool call counts by provider/tool
- duplicate guard behavior
- latency
- input/output/cached tokens
- total estimated cost
- completion guard success rate

Only after this comparison should Jarvis consider making Responses the default OpenAI tool-routing mode.

### Phase 8: Optional cleanup

If OpenAI and xAI continuation are both stable, then consider a small shared interface.

That cleanup should be boring and mechanical:

- no behavior change
- no provider feature changes
- tests proving xAI continuation still works
- provider-specific escape hatches preserved

Until then, duplication is acceptable because xAI took real effort to stabilize and should not be disturbed by an OpenAI experiment.

## Acceptance Checks

Minimum local tests before enabling the flag broadly:

```bash
source /home/boss/jarvis-venv/bin/activate
python -m pytest tests/test_openai_tool_schema.py
python -m pytest tests/test_xai_native_continuation.py
python -m pytest tests/test_orchestrator_usage_passthrough.py
python -m pytest tests/test_response_formatter.py
```

New tests to add with implementation:

```text
tests/test_openai_responses_adapter.py
tests/test_openai_responses_continuation.py
```

Manual smoke tests:

```text
1. OpenAI Q&A: no previous_response_id used.
2. OpenAI one-tool request: tool call parsed and executed.
3. OpenAI multi-tool request: in-flight second router turn uses local context first.
4. OpenAI server-side web search enabled: `SERVER_SIDE_TOOL_WEB_SEARCH` appears in usage, logs, saved response, and Web UI toast.
5. OpenAI server-side tools disabled by UI/client search hint: no OpenAI server-side tool calls are sent.
6. OpenAI continuation enabled: second router turn sends function_call_output + previous_response_id.
7. Later Web UI follow-up: no previous_response_id is sent; local Jarvis context is used.
8. xAI same tests: existing xAI continuation behavior unchanged.
9. OpenAI continuation rejection: one retry with local text context, no structural item sent to Chat Completions.
```

## Open Questions

- Should OpenAI Responses be enabled only when tools are present, or also for no-tool OpenAI chat once stable? Current lean: yes, move no-tool OpenAI chat to Responses after tool routing is stable.
- Should OpenAI in-flight continuation use `store=true` explicitly, or rely on default storage behavior when enabled? Current lean: Jarvis remains the source of truth; only use provider storage for explicit in-flight continuation, never as memory.
- What is the safest retention window for OpenAI in-flight response ids if they are never persisted beyond one request?
- **Resolved:** The adapter passes OpenAI **`prompt_cache_key`** (and optional **`prompt_cache_retention`**) on `responses.create` per the prompt caching docs. Use explicit **`OPENAI_PROMPT_CACHE_KEY`** or leave it empty for a derived stable key (**`OPENAI_PROMPT_CACHE_NAMESPACE`** + API-key–based digest). Telemetry logs whether a key was set, not its value.
- Which OpenAI server-side tools should Jarvis expose first after web search proves stable?
- Should OpenAI web search use `include=["web_search_call.action.sources"]` by default, debug-only, or never?
- Should OpenAI server-side tool budgets count output items, provider usage counters, or both?
- Should OpenAI vision analysis move to Responses eventually, or stay on the direct Chat Completions vision path? Current lean: move OpenAI vision to Responses after the main adapter is stable.
- What exact OpenAI error shapes indicate expired, missing, or incompatible `previous_response_id`, and how should they map to Jarvis fallback reasons?
- Should `OPENAI_RESPONSES_RESULT_MAX_CHARS` share the xAI serializer budget or have an OpenAI-specific default? Current lean: give OpenAI its own default.
- How should OpenAI Code Interpreter generated files be stored or surfaced if that tool is enabled?

## Working Decision

Treat OpenAI Responses as an adapter-local OpenAI experiment first.

Do not generalize xAI continuation yet.

Treat OpenAI server-side tools as provider-native evidence metadata that flows through the existing `server_side_tools` path, not as normal Jarvis client-side tool choices.

Do not use provider-native continuation for normal Q&A or later Web UI follow-ups.

Use `previous_response_id` only for single-tool and multi-tool in-flight Jarvis loops, and only after a successful Jarvis tool execution has produced a structural result that can be linked back to the provider's tool call id.
