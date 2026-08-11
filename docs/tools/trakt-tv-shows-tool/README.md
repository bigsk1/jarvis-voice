# Trakt TV Shows Tool

`trakt_tv_shows` adds public TV-series discovery and metadata to Jarvis through
the Trakt API v2. It works independently for mood-based recommendations, title
search, show details, related-series discovery, current public lists, and
trailer/video metadata.

## Configuration

Create a Trakt application and place its **Client ID** in the active mode env:

```bash
TRAKT_API_KEY="your-client-id"
```

The same Client ID can enable both `trakt_movies` and `trakt_tv_shows`. The
manifest uses `availability.all_of_env`, so the TV tool is absent from the
effective registry when the active cloud/local mode does not contain the key.
No Client Secret, account OAuth token, watch history, ratings, or watchlist is
used by this public-metadata integration. Those account reads belong to the
separate `trakt_account` tool.

## Network routing

The manifest uses `proxy_policy: prefer`. Requests use the shared Jarvis HTTP
client, trying `LOCAL_PROXY`, then `LOCAL_PROXY2`, then direct fallback. With
no configured proxy, requests start direct. This policy is limited to the tool.

## Actions

| Action | Purpose |
|--------|---------|
| `recommend` | Blend related shows from up to three favorites with bounded trending, streaming-ranked, and popular candidates; apply mood/genre/episode-runtime constraints and retrieve top-candidate videos |
| `search` | Search public TV-show metadata by title or text |
| `details` | Retrieve full public metadata for one Trakt show slug or supported external ID |
| `related` | Retrieve shows related to one resolved title |
| `videos` | Retrieve public trailer/video metadata |
| `trending`, `popular`, `anticipated`, `streaming` | Retrieve bounded public discovery lists |

`recommend` accepts a natural-language `request`, optional
`reference_titles`, and explicit `genres`, `exclude_genres`, `years`,
`runtimes`, or `ratings`. Natural requests also recognize exclusions such as
`no animation`, `no animated shows`, `without anime`, and `non-anime`.
Trakt has no documented provider-side exclusion parameter, so Jarvis
over-fetches a bounded candidate pool and enforces excluded genres locally.
Runtime always means a typical episode runtime. It is not the total duration
of a season or series.

## Trust and availability boundaries

- Titles, overviews, links, and video metadata are external, untrusted content.
- Trakt image URLs are omitted. Use `tmdb_tv_shows` when series artwork is
  requested; neither tool depends on the other for standalone use.
- A show appearing in Trakt's streaming list is only a discovery signal. It
  does not name a provider or prove regional availability or entitlement.
- Public metadata does not personalize from a Trakt account. Account history
  would require a separate OAuth feature.

## TV Night workflow

`/tv_night <mood, constraints, or favorite shows>` requires
`trakt_tv_shows`. It optionally uses `tmdb_tv_shows` for bounded artwork and
series commitment metadata, `serpapi_youtube_search` for a visible trailer
result, and `brave_llm_context` for current US streaming evidence. Missing
optional tools degrade the run without hiding the recipe.

Example:

```text
/tv_night thoughtful mystery like Severance and Dark, episodes under an hour, preferably a completed series
```

For a scheduled premiere watch, `/upcoming_tv_radar <genre criteria>` uses
TMDB's first-air-date and provider-side genre filters, maintains one Canvas
page per resolved primary genre, and keeps a shared emailed-show ledger across
genre schedules.

For optional personalized recommendations, watchlist, history, ratings, and
up-next progress, configure the separate read-only
[`trakt_account`](../trakt-account-tool/README.md) tool. The public TV tool
remains available with only a Client ID.
