# Personal Web Prompts

Put machine-specific or private Jarvis Web `@prompts` in this directory. Personal
prompt files are ignored by Git and override shared prompts with the same filename.
This README is documentation only and does not appear in the Web UI prompt menu.

## Create a prompt

Create a Markdown file whose filename is the command you want to type. For example,
`social_clip.md` is invoked with:

```text
@social_clip your topic here
```

A minimal prompt looks like this:

```markdown
# Social Clip

Turn the user's topic into a short social clip request, then call the appropriate
tool. Apply these instructions to the user's request below.
```

Everything in the file is sent to Jarvis as additional guidance for that request.
The text following `@social_clip` remains the user's request.

## Prefer specific tools

Optional YAML frontmatter can attach one or more `#tool` hints automatically:

```markdown
---
tool_hints:
  - create_social_clip
---

# Social Clip

Create the requested social clip and call `create_social_clip` when it is available.
```

Tool hints are strong preferences, not replacements for the prompt instructions or
tool schema. When a prompt declares exactly one tool hint, Jarvis treats that tool
as required: the prompt is hidden unless the tool is enabled, available in the
active mode/profile, and allowed by Jarvis Web.

Leave `tool_hints` out of general prompts and prompts that can use several tools or
native provider capabilities. This keeps those prompts available when any one
optional tool is disabled.

Use exact tool names from the Web UI tool list. The `tool_hints` value must be a YAML
list of non-empty strings.

## Shared and personal prompts

- Shared prompts live one directory above this one and are committed to the repo.
- Personal `*.md` prompts in this directory stay local because they are Git-ignored.
- A personal prompt overrides a shared prompt with the same filename.
- Keep reusable instructions in the prompt; keep the tool's real argument and
  capability limits in its tool schema.

After adding or editing a prompt, restart Jarvis Web if the server code changed and
hard-refresh the browser so its prompt registry reloads.
