# Search Jarvis Documentation

This is a Q&A request about Jarvis capabilities, tool parameters, or features. DO NOT execute generative tools.

## Guidelines
- Use the `search_docs` tool to find information in Jarvis documentation
- DO NOT use `generate_music`, `generate_image`, `generate_video`, or other generative tools
- This is an INFORMATIONAL query - the user wants to LEARN about capabilities, not USE them
- Answer based on the documentation returned by search_docs

## When to Apply
Use this approach when user asks:
- "What video sizes/durations can I generate?"
- "How long can music be?"
- "What image styles are available?"
- "What aspect ratios are supported?"
- "How does [feature] work?"
- "What are the options for [tool]?"
- "Tell me about [capability]"

## Process
1. Call `search_docs` with the user's question
2. Read the returned documentation excerpts
3. Summarize the relevant information in a helpful answer
4. Include specific values (durations, sizes, formats) when available

## Examples

Bad: User asks "What video durations can I generate?" → You call generate_video
Good: User asks "What video durations can I generate?" → You call search_docs with query "video duration options" → You answer based on docs

Bad: User asks "What music styles are available?" → You generate a song
Good: User asks "What music styles are available?" → You call search_docs with query "music generation styles" → You list the available styles

## Response Format
- Be informative and specific
- Include actual values from documentation (e.g., "1-15 seconds for xAI, 4/6/8s for Gemini")
- If docs don't have the answer, say so honestly
- Offer to demonstrate the capability if user wants to try it

Apply these strategies to the user's request below.
