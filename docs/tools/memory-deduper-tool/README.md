# Memory Deduper Tool

Detects duplicate/conflicting memories, assigns confidence scores, and proposes safe cleanup actions.

## Files

| File | Purpose |
|------|---------|
| `skills/memory_deduper.py` | Core logic for analysis + apply modes |
| `skills/memory_deduper.tool.json` | Tool schema and parameter definitions |
| `jarvis-web/server/sockets/chat.py` | Follow-up context extraction (`stash_ref`, `canvas_page_id`) |

## What It Does

`memory_deduper` has 2 modes:

1. `analyze`
- Scans memory entries
- Finds:
  - exact duplicate groups
  - probable duplicate groups
  - potential conflicts
- Scores confidence for each memory (0-100)
- Can save markdown report to stash and/or canvas

2. `apply`
- Executes dedupe actions for selected `group_ids`
- Keeps a primary memory in each group, deletes others
- Supports safety:
  - `dry_run=true` (recommended first)
  - `apply_mode=exact_only` (safest default)

## Detection Logic

### Exact duplicate group
Same:
- `category`
- normalized `key`
- normalized `value`

Suggested action:
- `keep_primary_delete_others`

### Probable duplicate group
Within same category:
- key similarity >= `key_similarity_threshold` (default `0.82`)
- value similarity >= `value_duplicate_threshold` (default `0.90`)

Suggested action:
- `review_then_merge`

### Potential conflict
Within same category:
- key similarity >= threshold
- value similarity <= `value_conflict_threshold` (default `0.45`)

Suggested action:
- manual review, prefer higher confidence unless domain says otherwise

## Confidence Score (0-100)

Confidence is heuristic, based on:
- Importance (weighted heavily)
- Recency (`updated_at` / `created_at`)
- Source reliability (e.g. `user_conversation` > generated/import sources)
- Value quality (too short gets lower score)
- Security penalty (`security_flag` in metadata)

Use confidence to rank cleanup decisions, not as absolute truth.

## Safe Usage Workflow

1. Analyze first
2. Review exact/probable/conflict groups
3. Run apply with `dry_run=true`
4. Run apply with `dry_run=false` only for approved `group_ids`

Recommended first run:

```json
{
  "action": "analyze",
  "scan_limit": 1200,
  "max_output_groups": 20,
  "save_to_stash": true,
  "save_to_canvas": false
}
```

Safe apply preview:

```json
{
  "action": "apply",
  "group_ids": ["exact_abc123def0"],
  "apply_mode": "exact_only",
  "dry_run": true
}
```

Real apply:

```json
{
  "action": "apply",
  "group_ids": ["exact_abc123def0"],
  "apply_mode": "exact_only",
  "dry_run": false
}
```

## Parameters

| Param | Type | Default | Notes |
|------|------|---------|------|
| `action` | string | `analyze` | `analyze` or `apply` |
| `group_ids` | array | `[]` | Required for `apply` |
| `apply_mode` | string | `exact_only` | `exact_only` or `exact_and_probable` |
| `dry_run` | bool | `true` | Always test first |
| `include_categories` | array | `[]` | Optional allowlist |
| `exclude_categories` | array | `["stash_artifact"]` | Optional blocklist |
| `scan_limit` | int | `1200` | Max memories scanned (<=5000) |
| `max_pair_checks` | int | `60000` | Pairwise similarity cap |
| `max_output_groups` | int | `20` | Output trimming cap |
| `key_similarity_threshold` | float | `0.82` | Key similarity floor |
| `value_duplicate_threshold` | float | `0.90` | Probable duplicate floor |
| `value_conflict_threshold` | float | `0.45` | Conflict ceiling |
| `save_to_stash` | bool | `true` in analyze | Saves markdown report |
| `save_to_canvas` | bool | `false` | Optional canvas page |

## Output Shape

Top-level:
- `ok`
- `speech`
- `data`

`data` includes:
- `summary`
- `exact_duplicate_groups`
- `probable_duplicate_groups`
- `conflicts`
- `apply_result` (for apply mode)
- `stash_ref`, `canvas_page_id` (if saved)

## Practical Notes

- Default excludes `stash_artifact` because those are often expected to be repetitive.
- Pairwise checks are capped; increase `max_pair_checks` for deeper scans on large memory sets.
- `exact_and_probable` can be destructive if thresholds are too loose. Use only after manual review.
- If your memory set is very large, run per-category (`include_categories`) to reduce noise.

## Troubleshooting

### "No exact groups found"
Normal on clean data. Check probable/conflict sections instead.

### Too many false conflicts
Raise `value_conflict_threshold` slightly (e.g. `0.50`) or tighten category filters.

### Too many probable duplicates
Increase `value_duplicate_threshold` (e.g. `0.93` to `0.96`).

### Analysis is slow
Lower:
- `scan_limit`
- `max_pair_checks`

Or run per-category with `include_categories`.

