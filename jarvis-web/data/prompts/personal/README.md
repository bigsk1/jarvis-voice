# Personal Web Prompts

Put machine-specific or private Jarvis Web `@prompts` in this directory. Personal
prompt files are ignored by Git and override shared prompts with the same filename.
This README is documentation only and does not appear in the Web UI prompt menu.

A saved `@prompt` is guidance placed before whatever task you type. The chat box
is still the task, and an empty task is rejected. Use the saved text to describe
how Jarvis should handle a request; supply the actual request after the `@prompt`.
For example, select `@code_review` and then paste the code or diff to review.

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

With two or more hints, the prompt keeps the existing group visibility behavior.
Unavailable individual hints are removed by the normal send path. The Settings
preview shows active and inactive hints without changing either rule.

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

## Manage prompts in Jarvis Web

Open **Settings → Prompts** to view every shared and personal prompt, including a
prompt that is not currently in the live `@` menu. The active mode/profile preview
explains current availability. You can create, duplicate, edit, and delete personal
prompts there. Editing a built-in creates a personal override; **Restore built-in**
deletes only that override.

Saving validates the snake-case-compatible filename, YAML, content size, and hint
shape. Environment-specific or unknown tool hints are warnings because the prompt
may be intended for another profile or machine. Changes made through Settings
refresh the current page's command registry immediately.

Native and Docker Web use this same personal directory. Docker Compose bind-mounts
only this private subdirectory read-write, so personal prompts remain outside the
image and survive container recreation.
