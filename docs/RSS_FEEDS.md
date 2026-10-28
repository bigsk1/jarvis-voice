# RSS feeds and daily digests

`rss_feed` reads public RSS/Atom feeds without an API key. The optional
`/rss_digest` workflow uses your configured interests to shortlist fresh
stories, read selected articles when needed, and publish a concise Canvas page.
It uses the existing workflow engine and configured chat provider.

No recurring task is installed automatically. Build and test the digest manually
before choosing a schedule.

## Setup

From the repository root:

```bash
cp config/rss_feeds.yaml.example config/rss_feeds.yaml
```

Edit the private `config/rss_feeds.yaml` file. It is gitignored, excluded from
Docker images, and reloaded on each tool call. Existing Docker config mounts
make it available inside Jarvis containers. JSON syntax is also valid in this
YAML file; the filename stays `rss_feeds.yaml`.

The [example](../config/rss_feeds.yaml.example) supplies a `daily_tech` profile
with public technology feeds. Replace or extend those sources and preferences.
A minimal profile looks like this:

```yaml
v: 1
profiles:
  daily_tech:
    canvas_title: Digests/Daily Tech
    interests:
      - Useful developer tools and practical self-hosting
    exclude:
      - Celebrity news and investment hype
    max_stories: 8
    max_candidates: 40
    max_age_hours: 48
    feeds:
      - name: Hacker News
        url: https://news.ycombinator.com/rss
        priority: normal
        enabled: true
```

| Setting | Behavior |
| --- | --- |
| Profile name | Exact argument to `/rss_digest`; letters, digits, `_` and `-`, up to 64 characters. |
| `canvas_title` | Stable page title; defaults to `Digests/<profile>`. Use a distinct title for each profile. |
| `interests`, `exclude` | Lists of descriptions used by the editorial model. Exclusions are explicit prompt constraints, not a deterministic semantic filter. |
| `max_stories` | 1–8; default 8. Fewer stories are allowed when evidence is thin. |
| `max_candidates` | 1–40; default 40 across all feeds in the profile. |
| `max_age_hours` | 1–720; default 48. Uses publication date, falling back to an actual update date. |
| `feeds` | 1–16 configured feeds per profile; each needs `name` and public HTTP(S) `url`. At least one must remain enabled. |
| Feed `priority` | `high`, `normal` or `low`; default `normal`. Controls fetch order and serves as an editorial tiebreaker, not a guarantee of accuracy. |
| Feed `enabled` | Set `false` to skip that source. |

This feature adds the `feedparser` Python dependency. Update the Python
environment that actually runs Jarvis using the repository requirements; the
[native install guide](INSTALL_GUIDE.md) describes that environment. Development
uses `uv sync --dev` in the repo. Docker installations must rebuild the Jarvis
image and recreate the affected services; retain any overlay `-f` arguments:

```bash
docker compose up -d --build
```

The workflow needs `rss_feed`, `canvas`, and a configured LLM. Article enrichment
uses the existing optional `crawl_url` tool and its `CRAWL4AI_URL` /
`CRAWL4AI_API_KEY` settings. Without Crawl4AI, the digest can use feed content
and clearly labeled feed-description notes. It must not claim to have read an
article from its headline alone. Normal tool-profile and request restrictions
still apply.

After installing a new tool, follow the normal [tool discovery and sync
instructions](../skills/README.md#tool-discovery) for each mode you use. Editing
an existing feed profile does not itself need another tool sync or restart.

## Try it manually

Ask Jarvis to list RSS profiles, or call:

```json
{"action":"list_profiles"}
```

Pass `profile` with `list_profiles` to inspect one named group when several
profiles would make the result too large.

The listing includes profile interests and exclusions, plus configured feed
names, URLs and priorities. Large listings may be shortened in model context.

For a direct feed read, use `rss_feed` with:

```json
{"action":"read","url":"https://news.ycombinator.com/rss","limit":10}
```

Direct reads do not need a profile file, generate a digest, or advance
publication history. The item limit is 1–20, default 10; the direct read uses a
48-hour lookback. Entries with neither a usable publication date nor update
date are skipped and counted as undated.

Direct-answer model context includes feed-provided excerpts of at most 1,200
characters per item within a shared 6,000-character result budget. Saved
follow-up history keeps metadata and summaries, not those bodies. These excerpts
are not proof that a complete remote article was read.

In Jarvis Web or the production CLI, run:

```text
/rss_digest daily_tech
```

Omitting the profile uses `daily_tech`. The workflow is explicit or scheduled:
it is not offered through autonomous `workflow` discovery. This command changes
the profile's Canvas page and publication history; it is not a dry run.

The reading page contains a short **At a glance**, story summaries, why each
story matters, and source links. Feed diagnostics, batch IDs, raw JSON and tool
logs stay out of its editorial content. If no eligible candidates exist, or the
editor selects none, the current page is preserved and no publication is
acknowledged.

## Freshness, coverage and model use

Each read makes a fresh feed GET with `Cache-Control: no-cache, max-age=0` and
`Pragma: no-cache`; there is no saved HTTP response or stale-feed fallback.
These headers cannot guarantee that a publisher or CDN has updated its content.
Feed redirects receive the same public-address checks. Private/loopback URLs,
credential-bearing URLs and unsupported XML are rejected.

Profile collection fetches higher-priority sources first, with four concurrent
workers. It divides 40 seconds across the required worker waves, allowing up to
15 seconds per feed within a shared 45-second collection budget. It then takes
up to 20 recent entries per source, round-robin across successful sources before
applying the candidate limit. Undated entries and entries outside the lookback
are excluded. A newly fetched old headline is not treated as a new publication.

Content is labeled `inline`, `summary` or `out_of_line` through `content_kind`.
`content_chars` counts the feed-provided text before shortening, not the length
of the remote article; `content_truncated` records any cut. The reader caps feed
content at 6,000 characters, and profile staging caps it at 3,500. Summary-only,
out-of-line, short or truncated content requests article enrichment when selected.
A long teaser is still a summary. If enrichment fails, the writer must label an
available excerpt or omit the story rather than imply a complete article read.

A normal nonempty run makes two workflow-internal model calls:

1. Rank the bounded candidate metadata and return only IDs from that batch.
2. Write the digest from the validated selection and successful article reads.

The first dataset is limited to 40,000 serialized characters. The selected-story
dataset is independently limited to 40,000 serialized characters, shortening
feed prose while preserving complete IDs and URLs. Only selected stories that
need more content are crawled, at most eight, with Crawl4AI `cache_mode: bypass`.
Each selected URL gets one workflow tool call; there is no workflow-level
per-URL retry.
The workflow supplies at most 3,000 characters from each successfully read
article to the final model. These are **per-dataset limits**, not a total prompt
or token cap: instructions, interests, metadata and article excerpts add to the
final request. Provider context limits and normal LLM billing still apply.
An empty feed result uses no model calls; an empty shortlist uses one.

If some feeds fail, the remaining sources may produce a digest with a short
coverage note naming the first three failed sources and safe failure reasons,
plus a remaining count when needed. Structured `failed_feeds` identifies up to
16 sources, subject to the model-context budget. If every feed fails, the
workflow fails and keeps the old page and publication history. Failed or
unavailable article enrichment leaves only the actual feed evidence; summaries
must disclose that limitation or omit the story. A successful workflow is not
a guarantee of complete source coverage.

Feed requests use the tool's `prefer` proxy policy through the shared HTTP
client: configured proxies are preferred and direct fallback remains allowed.
Article crawling uses `crawl_url`'s separate transport and proxy settings.

## Publication history and recovery

Canvas `create` refreshes an existing exact-title page, so repeated successful
runs keep one current digest at the configured title. There is no automatic
daily archive or growing history appendix.

The workflow acknowledges a batch only after Canvas reports success. The feed
service then verifies the persisted page identity, title and recency, and checks
which selected source URLs actually appear. Only those published stories enter
the seen history. Unselected stories and selected stories omitted from the page
are not marked seen. A later fresh read can reconsider them only while they
remain in the publisher's feed, its recent 20-entry source window, the profile's
lookback and the bounded candidate pool. This is not a guaranteed backlog.
Reading or shortlisting alone does not mark a story as published.

History lives under private `data/rss-feeds/`, shared by cloud and local mode
for the same profile, just like its Canvas destination. URL normalization removes
known tracking parameters for identity. This suppresses repeated links, not all
different URLs reporting the same event; the editorial pass also groups duplicate
reporting. An updated article at an already published URL remains seen while its
receipt is retained. History is pruned after 90 days and limited to 5,000 IDs.

Staged batches expire after two hours or a profile change. Pending batches are
not evicted to make room for newer reads: each profile allows up to 20 pending
batches and retains up to five completed receipts. Its state file stays within
4 MB; old completed receipts are pruned first, and a transaction that still
exceeds either capacity fails without replacing the existing file. Finish an
active digest or wait for older pending batches to expire before reading again.

Concurrent selections of overlapping stories are held apart for up to 15
minutes. If a run fails after shortlisting, wait for that claim to expire before
retrying overlapping stories.
If Canvas succeeds but acknowledgment fails, inspect the saved page and the
failed step: the page can exist while seen history remains unchanged. No email,
webhook or notification is sent by this workflow.

For later automation, use the existing [Scheduled Tasks](tools/scheduled-tasks/scheduled-tasks.md)
workflow type with ID `rss_digest` and query `daily_tech`. Choose a timezone,
allow enough time for article reads, and leave overlaps disabled. No schedule
has been created as part of this feature; manual verification comes first.
