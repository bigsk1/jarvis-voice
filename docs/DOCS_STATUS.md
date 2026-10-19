# Documentation maintenance

Use the [documentation index](README.md) to find the current user and contributor
guides. This page describes how to keep those guides useful as Jarvis changes.

## Write for the page's reader

A public feature guide should answer:

1. What does the feature do, and when would someone use it?
2. What must be installed, configured, or enabled?
3. How does the user start, operate, and stop it?
4. What are its current limitations and common failure modes?
5. Where are the detailed API, configuration, and contributor references?

Describe current behavior directly. Replace completed build phases, hand-off
notes, preview reviews, and conversations with one operator with explanations
that make sense to someone cloning the repository for the first time. Keep
useful technical detail; changing the audience does not require reducing every
guide to a short overview.

Contributor pages can document architecture, invariants, and reproducible test
commands. Record one-session test totals, temporary harness paths, machine-specific
measurements, and preview-by-preview reviews in development notes or release
records, rather than presenting them as permanent setup instructions.

## Separate current behavior from proposals and history

- Put supported setup and behavior in the relevant feature guide.
- Mark research and future designs explicitly as proposals. A plan is not an
  available command or API contract.
- Keep public historical decisions under `archive/` when they help explain a
  current tradeoff, and link readers back to the active guide.
- Keep operator-specific notes in ignored local folders such as `docs/personal/`.
  Public pages must not depend on files that a fresh clone does not contain.

Do not copy changelogs or implementation checklists into a feature guide simply
because a feature was delivered in several stages. Preserve current limitations
without describing the whole debugging session that discovered them.

## Verify instructions against the checkout

Check command paths, launcher options, example configuration, and the actual
caller before changing a claim. Distinguish startup mode, request/data mode,
provider selection, foreground execution, and optional background jobs. Use
portable paths and placeholders instead of one operator's host or temporary files.

Provider model IDs, prices, tool counts, and passed-test counts drift. Keep their
source of truth clear and avoid duplicating exact values where a maintained
reference is more useful. Third-party documentation snapshots should retain their
version and must not be presented as current upstream documentation.

When changing headings or moving pages, update incoming links and preserve
useful anchors. Keep screenshots and relative image paths usable on GitHub as
well as in the local Docs viewer.

## Check documentation changes

From the repository root:

```bash
.venv/bin/python -m pytest tests/test_docs_integrity.py -q
git diff --check
```

These checks cover relative links, fence structure, and selected mode/config
contracts. Also inspect changed heading links, example commands, and rendered
structure. A documentation-only cleanup does not require starting providers,
changing live databases, or restarting services.

Runtime changes should follow the broader [testing guide](TESTING.md).

## Keep private notes out of published search

Git tracking and the QMD collection are separate boundaries. QMD does not use
`.gitignore` as its exclusion policy. Check the configured collection and
[QMD exclusions](qmd/README.md#excluding-directories) before updating an index
that also contains private local directories. Index maintenance is a separate
operation from editing documentation.
