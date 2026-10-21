# OpenCode V2 agent selection

Jarvis's `opencode` tool accepts `agent_mode: "build"` or `"plan"` and defaults
to `build`. The bridge sends the selected agent when creating its V2 session.
The agent and model are separate selections: `OPENCODE_PROVIDER` and
`OPENCODE_MODEL` choose the model for Jarvis coding tasks.

| Agent | Intended use | Permission implications |
| --- | --- | --- |
| `build` | Implement, test, and debug workspace projects | Uses configured permissions and workspace controls |
| `plan` | Inspect code and propose work without normal project edits | Built-in policy denies ordinary edits, but shell and other actions remain permission-controlled |

Build mode does not override global permission rules or the workspace plugin.
Plan mode is not a process sandbox or a guarantee that an arbitrary shell
command cannot change files. OpenCode's effective policy and the Linux service
filesystem restrictions are what constrain tool execution.

Example explicit plan-mode tool input:

```json
{
  "task": "Review the workspace utility and propose improvements. Do not modify files.",
  "agent_mode": "plan"
}
```

Jarvis does not have an interactive relay for OpenCode questions and permission
requests. A pending request is surfaced as a blocker and the unattended session
is interrupted. Do not configure `ask` expecting Jarvis to approve it silently.

## OpenCode's own agents

V2 can run child agents, including background agents. Those agents execute
inside OpenCode and are distinct from Jarvis's tools or durable background-task
system. Configured child agents have their own permissions; the parent's
subagent permission controls which agents it may launch.

A global plugin and the systemd service restrictions apply to work executed on
that OpenCode server, including its children. The Jarvis request still waits
for its supervised coding result and retains its own cancellation/deadline.
Do not treat a task-admission receipt or a background-agent launch as the final
Jarvis answer.

Custom OpenCode agents can be configured under `agents` in `opencode.json` or
as Markdown definitions in `.opencode/agents/` and
`~/.config/opencode/agents/`. Jarvis currently exposes only `build` and `plan`
through its tool schema. See the upstream
[agents documentation](https://opencode.ai/v2/docs/agents/) for the complete
V2 configuration and [permissions](OPENCODE_PERMISSIONS.md) for Jarvis's setup.

The proposed loop in which Jarvis answers OpenCode questions, steers a running
agent, and resumes a previous project across separate requests remains future
work. Current behavior is documented in [OPENCODE.md](OPENCODE.md).
