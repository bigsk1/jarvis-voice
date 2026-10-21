# OpenCode V2 API used by Jarvis

Jarvis targets the OpenCode 2.x server API. The default native address is
`http://localhost:4096`; the configured `OPENCODE_BASE_URL` can point elsewhere.
Send HTTP Basic authentication when `OPENCODE_SERVER_PASSWORD` is configured.
V2's Basic-auth username is fixed to `opencode`.

The upstream [V2 API reference](https://opencode.ai/v2/docs/api) defines the
wire contract. This document describes the Jarvis-facing subset, not every
OpenCode endpoint. Experimental routes can change between releases; upgrade the
client and server together and rerun the integration checks.

## Task lifecycle

| Operation | V2 route | Meaning |
| --- | --- | --- |
| Server health/version | `GET /api/info` | Read running server identity and version |
| Create a session | `POST /api/session` | Return a session under `data` |
| Select its model | `POST /api/session/{sessionID}/model` | Select the requested provider/model |
| Get a session | `GET /api/session/{sessionID}` | Read session state and outcome |
| List sessions | `GET /api/session` | Read `data` plus pagination cursors |
| Admit task input | `POST /api/session/{sessionID}/prompt` | Queue input; response is an admission receipt |
| Add context without running | `POST /api/session/{sessionID}/synthetic` with `resume: false` | Admit synthetic context without starting execution |
| Wait for idle | `POST /api/experimental/session/{sessionID}/wait` | Return 204 when the agent loop is idle |
| Read messages | `GET /api/session/{sessionID}/message` | Read projected messages with pagination |
| Interrupt execution | `POST /api/session/{sessionID}/interrupt` | Interrupt active execution; an idle session is a no-op |
| Subscribe to progress | `GET /api/event` | Receive server-wide SSE events |
| Pending permissions | `GET /api/session/{sessionID}/permission` | Detect unattended permission requests |
| Pending forms | `GET /api/session/{sessionID}/form` | Detect questions/forms needing a reply |

The V1 routes `/session`, `/event`, `/config`, and `/session/{id}/abort` are not
the V2 integration contract. In particular, a successful prompt POST does not
mean that code has been written or that an assistant answer is available.

## Representative wire shapes

Create a session with the chosen location, agent, and model:

```json
{
  "title": "Build a workspace utility",
  "agent": "build",
  "model": {"providerID": "xai", "id": "grok-4.7"},
  "location": {"directory": "/home/example/jarvis-workspace"}
}
```

The model reference uses `id`, not V1's `modelID`. The returned session is
wrapped in `data` and contains its `id` and location.

Submit the task to that session:

```json
{
  "text": "Create a hello world script in projects/scripts/example.",
  "resume": true
}
```

The response's `data` describes admitted user input. Jarvis observes completion
and correlates the final assistant message with that input. It does not reuse
an earlier answer when delivery or completion cannot be confirmed. List responses use `data` and
`cursor`; callers must follow the returned pagination cursors instead of
assuming one response contains the whole conversation.

V2 assistant messages have `type: "assistant"` and a `content` array containing
text, reasoning, or tool items. Jarvis extracts final displayable text and
normalizes it for existing Jarvis result consumers. The tool's normalized
result is not an unmodified OpenCode HTTP response.

## Progress and recovery

`/api/event` includes events across locations and sessions. Jarvis filters the
stream to the task's session, normalizes bounded status text, and falls back to
persisted session/message state when events are absent or disconnected. The
stream is volatile; a disconnect can lose events. Receiving an idle event alone
is not sufficient evidence that the submitted task succeeded.

The bridge preserves a task deadline, cancellation, errors, permission blockers,
and question/form blockers while waiting. It interrupts unattended blocked runs
and reports the issue to Jarvis. Reasoning deltas, raw command output, and
unbounded tool payloads are not forwarded as Web progress.

Use `./tests/integration/test-opencode-integration.sh` for deterministic
transport/tool coverage. `--health cloud|local` checks the configured server
without a model request; `--live cloud|local` creates a real plan-mode session.
See [the integration guide](OPENCODE.md) for setup, logging, and boundaries.
