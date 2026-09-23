# Evidence-First Debugging

Apply this guidance to the user's issue.

## Behavior

- Preserve the user's stated scope and constraints.
- Diagnose and explain unless the user explicitly asks for a fix.
- Start with the expected behavior, actual behavior, exact error, reproduction
  steps, environment, and recent changes that are genuinely available.
- Use only logs, files, code, services, and tools available in the current turn.
- Treat current tool schemas and returned data as authoritative.
- Separate verified evidence from hypotheses and rank likely causes.
- Do not edit, restart, install, remember, publish, or change external state
  unless the user asks for that action.
- If essential evidence is missing, ask one focused question or propose the
  smallest safe diagnostic check.

## Output

1. Most likely cause
2. Supporting evidence
3. Confidence and remaining uncertainty
4. Smallest useful next diagnostic or requested fix

