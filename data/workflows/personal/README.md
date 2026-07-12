# Personal workflows

Put private workflow JSON files in this folder when they should work locally but not be committed to GitHub.

- `*.json` files here are gitignored.
- They load through the same `WorkflowLoader` as shared `data/workflows/*.json` files.
- A personal workflow with the same `id` as a shared workflow overrides the shared workflow locally.
- Use explicit slash triggers, just like shared workflows.

Example:

```json
{
  "id": "my_private_workflow",
  "name": "My Private Workflow",
  "enabled": true,
  "triggers": {
    "explicit": ["/my_private_workflow"]
  },
  "steps": [
    {
      "step": 1,
      "tool": "get_time",
      "params": {}
    }
  ],
  "success_speech": "Private workflow complete."
}
```
