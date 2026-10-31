# Hand a Jarvis task to another agent

Ask Jarvis to send a task, plus selected Stash files or Canvas pages, to an agent that already receives Jarvis webhooks. GrokBot is the included example. The same handoff works for any receiver that accepts the destination contract and can reach the Jarvis API.

You might say:

“Ask GrokBot to double-check this research, including the transcript in Stash.”

Jarvis sends that through the existing `send_webhook` tool. The other agent answers in its own chat. Jarvis does not add a separate tool, workflow, or service, and it does not place that answer back in the Jarvis conversation unless you explicitly ask for a follow-up round trip.

## What you need

1. A named destination in `config/webhook_registry.json`, with its URL and credentials already configured.
2. `"artifact_handoff": "jarvis_v1"` on that destination. Leave the URL, authentication, routing, and existing body contract in place.
3. A receiver whose schema allows the new fields inside `context`.

`config/webhook_registry.json.example` contains a disabled `grokbot` starter with no real URL or secret. Merge the fields you need into your own registry. Replacing the registry file would drop destinations you already use.

Set these values in the private ENV for each Jarvis mode that will send handoffs (`config/cloud.env` or `config/local.env`). Both ENV examples include the placeholders:

```bash
GROKBOT_POST_URL="https://receiver.example.invalid/webhook"
GROKBOT_WEBHOOK_KEY="replace-with-the-receiver-token"
# Optional for a custom header mapping in your registry:
# GROKBOT_WEBHOOK_HEADER_KEY=""
```

The starter entry reads `${GROKBOT_POST_URL}` for its URL and sends `Authorization: Bearer ${GROKBOT_WEBHOOK_KEY}`. Store only the raw token in `GROKBOT_WEBHOOK_KEY`. `GROKBOT_WEBHOOK_HEADER_KEY` is available for receiver-specific header mappings; setting it alone has no effect because the starter does not reference it. After filling in the required settings, enable the destination in your private registry. Docker uses these same selected-mode ENV files; its root Compose `.env` does not replace them.

For retrieval and a requested return trip, the receiving agent separately stores its own `JARVIS_API_URL` and `JARVIS_API_KEY`. The Jarvis API key is distinct from the receiver's webhook token.

Text-only requests keep working. If you do not select any artifacts, Jarvis sends the body unchanged.

## What you send

Use the destination name and a normal v1 body:

```json
{
  "webhook": "grokbot",
  "data": {
    "v": 1,
    "id": "jarvis-handoff-unique-for-this-task",
    "source": "jarvis",
    "type": "question",
    "task": "Check this research for errors. Read the selected transcript and Canvas page. Report your findings in this chat.",
    "reply": "chat",
    "context": {
      "summary": "A concise account of the result and what needs checking.",
      "source_urls": ["https://example.com/source"],
      "stash_refs": ["stash://space_example/f_example"],
      "canvas_page_ids": ["page_example"]
    }
  }
}
```

Use a new `id` for each handoff. `type` may be `test`, `ping`, `task`, or `question`. The receiver’s `reply` value for this destination is `chat`, so the answer shows up in that agent’s chat. This contract has no priority field.

Replace the example references with real tool results. You can select up to 12 artifacts in total through `context.stash_refs` and `context.canvas_page_ids`.

A Stash selection can be a `stash://` string, or a result object that already contains `ref` or `stash_ref`. Those two fields are the same URI. The stash tool returns it as `ref`. Uploads and media tools return it as `stash_ref`. If a result object contains both, they must match. Jarvis keeps the URI and drops the rest of that object, including `path`. A `path` is a file location on the Jarvis host. The receiving agent cannot open it as a local file.

Leave the other tool field names as they are. Put only the context the task needs in the payload. Source URLs are notes for the receiver. Jarvis does not fetch them while sending.

Jarvis then adds `context.artifact_manifest`. Do not supply that field yourself.

```json
{
  "v": 1,
  "mode": "cloud",
  "availability": "not_checked",
  "artifacts": [
    {
      "kind": "stash",
      "ref": "stash://space_example/f_example",
      "mode": "cloud",
      "resolve_url": "/api/stash/resolve?ref=stash%3A%2F%2Fspace_example%2Ff_example&mode=cloud",
      "read_url": "/api/stash/read?ref=stash%3A%2F%2Fspace_example%2Ff_example&mode=cloud",
      "download_url": "/api/stash/download?ref=stash%3A%2F%2Fspace_example%2Ff_example&mode=cloud"
    },
    {
      "kind": "canvas",
      "page_id": "page_example",
      "read_url": "/api/canvas/page_example?include_content=true"
    }
  ]
}
```

`availability: "not_checked"` means Jarvis attached retrieval paths and did not open the files or test the receiver’s access. Stash links use `context.mode` when you set it, and otherwise the mode Jarvis was using when it sent the webhook. Canvas links use the existing Canvas API.

## How the receiver reads the files

The receiver combines its own Jarvis API origin with the relative path and sends `Authorization: Bearer <key>`. The webhook body never includes that origin or key. Any machine that can reach the Jarvis API can do this: the same host, another computer on the network, or a remote agent. The routes use the API authentication you have already configured.

| Need | Route |
| --- | --- |
| Resolve a file ID or filename to canonical metadata | `GET /api/stash/resolve?ref=...&mode=cloud` |
| Read paged UTF-8 text | `GET /api/stash/read?ref=...&mode=cloud` |
| Download original bytes, including PDF, image, audio, or video | `GET /api/stash/download?ref=...&mode=cloud` |
| Read a Canvas page as Markdown | `GET /api/canvas/{page_id}?include_content=true` |

All three Stash routes take the URI in the `ref` query parameter. Copy it from `ref` or from a `stash_ref` field, then pass it as `ref`. Resolve returns the canonical `stash_ref`, filename, MIME type, size, and relative read and download URLs.

Read follows `next_url` until `has_more` is false. Each page is 20,000 characters by default and 40,000 at most. Text files larger than 10 MiB, and files that are not UTF-8 text, are downloaded instead. A changed file between pages returns 409. Downloading a PDF, image, or audio file returns the original bytes. The receiver still needs its own tool to inspect that kind of file.

If Jarvis is offline, the reference has expired, or access is denied, the receiver should say what it could not open and what it could still check. Sending a handoff does not pin files or grant new access. Normal Stash retention can remove them later.

## What comes back

Jarvis applies the destination’s existing proxy, authentication, redirect, cooldown, and single-attempt rules. A bad selection, or a body the destination schema rejects, is stopped before anything is sent. The tool receipt keeps the handoff ID and a short list of artifact handles. A long chat history may drop older handles and record how many were omitted.

An HTTP success means the receiver accepted the webhook. It does not mean the agent finished the task or opened the files. If delivery is uncertain, check the receiver before sending the task again. The answer stays in the receiving agent’s chat.

### Ask for a follow-up in Jarvis

If the task says to continue in Jarvis, the receiver can upload its result with `POST /api/stash/upload`, then call `POST /api/query` once. The query text should include the returned `stash_ref`, the handoff ID, a short summary, and the next instruction. Jarvis answers that query back to the receiver. The receiver reports the outcome in its own chat.

That round trip is a separate request. It does not appear by itself in the original Jarvis Web conversation. Upload uses whichever Stash store the API process is using at the time, so the later query and retrieval should use that same mode. Put the file URI and the read instruction in `query`. A `session_id` only labels the request. It does not reopen a Web or CLI conversation.

Keep the full query response JSON in the receiver's API helper, including `data` and optional completion and error fields. A compact human display can be separate. Filtering the result to speech and tool names loses structured artifact references and outcome metadata needed for another handoff.

The [receiver setup prompt](GROKBOT_RECEIVER_PROMPT.md) is the instruction set to give the agent on the other side. It keeps existing text-only webhooks working while adding artifact retrieval.
