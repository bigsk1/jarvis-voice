# DeepWiki: public GitHub repository research

Jarvis uses the public [DeepWiki MCP server](https://docs.devin.ai/work-with-devin/deepwiki-mcp)
to read repository documentation and ask questions grounded in indexed code.
It needs no GitHub token, Devin account, Docker container, or additional Python
dependency. Requests go from Jarvis to DeepWiki over HTTPS; this does not expose
your Jarvis server to the internet.

Use this integration for public repositories. Do not put private code,
credentials, or confidential details in the question sent to this public service.

## Configuration

The following entry is enabled in `config/mcp-servers.json`, inside the existing
`mcpServers` object:

```json
{
  "deepwiki": {
    "type": "http",
    "url": "https://mcp.deepwiki.com/mcp",
    "description": "Public GitHub repository documentation and code Q&A through DeepWiki. Prefer focused questions; indexed documentation may lag the latest source revision.",
    "enabled": true
  }
}
```

Jarvis needs `type: "http"` as well as `url`. The public endpoint uses Streamable
HTTP; the older `/sse` endpoint is unnecessary. No authorization headers are set.
To disable the integration, set `enabled` to `false`, sync tools, and restart
the Jarvis processes that use it.

## Tools and discovery

| Jarvis tool | Use |
|---|---|
| `mcp_deepwiki_ask_question` | Ask a focused architecture, behavior, or implementation question. Accepts one repository or a list of up to ten. |
| `mcp_deepwiki_read_wiki_structure` | List one repository's documentation topics. |
| `mcp_deepwiki_read_wiki_contents` | Read one repository's wiki. This can return a large document; prefer a focused question for routine use. |

Pass repository names as `owner/repo`, for example `pallets/flask`. DeepWiki
does not expose page selection or pagination on `read_wiki_contents`.

After adding or enabling the server, sync Tool RAG for the modes you use. This
script requires the operator's Jarvis environment, rather than the repo `.venv`:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

Restart existing Web, voice, or CLI processes afterward so their in-memory
tool registry and Python modules load the changes. Existing tool profiles and
blocked-tool settings still apply.

Example requests:

- "Use DeepWiki to explain how pallets/flask handles request contexts."
- "Compare the architecture of these two public GitHub repositories."
- "Explain this repository's MCP integration and save a reference page to Canvas."

In Web, use `#mcp_deepwiki_ask_question` to explicitly prefer the question tool.
It still participates in the normal tool selection and execution path.

## Answers, citations, and larger results

Jarvis converts DeepWiki citation markup into Markdown links and retains a
bounded answer, repository names, sources, and the original question. Dedicated
context handling preserves this evidence for the immediate answer and later
Web follow-ups instead of reducing it to the generic MCP text preview.
Large citation lists are bounded too, with the total count and an explicit
omission flag; the full Markdown artifact retains every normalized citation.

Some full-wiki results cite relative source files without identifying the indexed
commit. For a single-repository request, Jarvis turns these into GitHub links to
the current default branch (`HEAD`) and labels them accordingly. A revision note
stays with the answer and saved Markdown: the current file and line numbers can
differ from the version DeepWiki indexed. Ambiguous references from multi-repo
answers remain text instead of being assigned to the wrong repository.

Answers longer than 6,000 characters are also saved as complete Markdown in
Stash. The response carries a `stash://` reference so Jarvis can read the full
document later through the existing Stash tool. Storage uses the configured
`STASH_DIR` and normal retention rules. If saving fails, the bounded answer
remains available with an explicit warning; no nonexistent artifact is advertised.

The full Markdown is useful reference material, not a permanent knowledge import.
Use Canvas to keep a curated page, or explicitly ask to add material to your
knowledge library. Citation conversion does not verify the model's claims.

Canvas creation remains a separate, existing tool call after research. Jarvis
can give a short chat response plus a Canvas page when requested or useful;
DeepWiki calls do not automatically create pages or a separate UI.

## Verification and troubleshooting

The MCP diagnostic can exercise only this server:

```bash
./bin/test-mcp --test deepwiki read_wiki_structure '{"repoName":"pallets/flask"}'
./bin/test-mcp --test deepwiki ask_question '{"repoName":"pallets/flask","question":"Explain request contexts and cite the relevant sources."}'
```

- **Repository not found:** public on GitHub does not mean indexed by DeepWiki.
  Visit `https://deepwiki.com/owner/repo` and follow its indexing instructions.
  Jarvis preserves this as a tool error, rather than inventing a repository
  summary or storing the error as a research artifact.
- **Old or incomplete answer:** check the wiki's indexed revision and consult
  the current GitHub source for version-sensitive details. The public MCP tools
  cannot request a particular branch or commit.
- **Missing tool in Web:** confirm the server is enabled, sync the active mode,
  check profiles and blocked tools, and restart the running process.
- **Timeout:** try a narrower question or one repository at a time. Jarvis's
  existing MCP timeouts still apply; this integration does not increase them
  for unrelated servers.
- **Expired artifact:** Stash retention still applies. Re-run the public query
  or save a lasting summary to Canvas.

See also [remote MCP transport](MCP_REMOTE_TRANSPORT.md),
[MCP quick start](MCP_QUICKSTART.md), and [Canvas](../CANVAS_SYSTEM.md).
