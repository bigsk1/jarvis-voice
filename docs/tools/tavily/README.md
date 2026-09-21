# Tavily search and extract

Jarvis exposes Tavily as two optional tools: `tavily_search` finds current web
sources, and `tavily_extract` reads one source more closely. They use Tavily's
[Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
and [Extract API](https://docs.tavily.com/documentation/api-reference/endpoint/extract)
directly. This keeps source URLs, excerpts, and usage metadata structured for
Jarvis Web cards, workflows, and later chat turns. The [remote MCP server](https://docs.tavily.com/documentation/mcp)
is available separately, but Jarvis's generic MCP result path currently treats
its output as text, so the direct tools are the better fit here.

Set `TAVILY_API_KEY` in `config/cloud.env` and/or `config/local.env`. The key is
read from the active mode, sent only in the HTTPS Authorization header, and
never placed in a URL or tool result. For normal Jarvis tool execution, the
Tavily child receives only this credential plus shared runtime settings through
the [local tool child environment policy](../../../skills/README.md#local-tool-child-environment).
It does not re-load all values from the mode env file. The policy reduces
accidental environment inheritance, although it is not a filesystem sandbox.
When absent, the tool availability gate
omits these tools from the active tool catalog. A restart and Tool RAG sync make
them discoverable:

```bash
# Use the interpreter documented in AGENTS.md for Tool RAG sync.
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

Example chat requests:

```text
Use Tavily to find current primary sources about the new Python release.
Use Tavily to extract the page at https://example.com/article.
```

`tavily_search` defaults to basic search with five results and no generated
answer or raw page bodies. Advanced search costs more credits. An optional
`time_range` uses strict published-date filtering, which can omit undated
sources. `tavily_extract` defaults to basic extraction and caps the returned
markdown at 12,000 characters. A `query` asks Tavily for relevant chunks; a
`max_chars` override can raise the cap to 20,000. Both tools mark external text
as untrusted. Search and extraction can consume Tavily credits.

These tools cover search and extraction only. Tavily Crawl, Map, and Research
are separate API operations and are not enabled by this integration.
