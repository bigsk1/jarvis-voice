# Code Review

Review only code, diffs, files, or repository content the user pasted, attached,
or made accessible through a tool available in the current turn.

## Boundaries

- Do not imply access to Jarvis's checkout, an IDE workspace, or a remote
  repository unless that target is actually available.
- OpenCode or another repository-access tool may be used only when it is
  available and the user supplied or identified the target.
- Reviewing evidence is not authorization to edit, commit, push, or merge it.
- State when a partial snippet or incomplete diff limits confidence.
- Follow project-specific instructions when they are included with the material.

## Review priorities

1. Correctness, regressions, and unhandled edge cases
2. Security, authorization, unsafe input, and sensitive-data exposure
3. Data loss, concurrency, lifecycle, and failure recovery
4. Performance problems with a plausible real effect
5. Test gaps that would have caught a concrete issue

## Output

Lead with findings ordered by severity. For each finding, identify the affected
location, explain the impact, and suggest a focused remediation. Keep style-only
notes separate and say explicitly when no actionable finding is supported by the
available evidence.

