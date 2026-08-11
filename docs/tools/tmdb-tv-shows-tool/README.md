# TMDB TV Shows Tool

`tmdb_tv_shows` is a standalone public TV-discovery, series-metadata, credits,
and artwork tool backed by TMDB. It can search and discover shows on its own or
complement `trakt_tv_shows` with posters, backdrops, logos, creators, aggregate
cast/crew, networks, seasons, episode counts, content ratings, and production
details.

## Configuration

Put at least one application credential in the active mode env:

```bash
TMDB_ACCESS_TOKEN="your-api-read-access-token"
# TMDB_API_KEY="your-v3-api-key"
```

The Read Access Token is preferred and sent as a Bearer credential. When it is
absent, the tool uses the v3 API key query parameter. The same credential can
enable both `tmdb_movies` and `tmdb_tv_shows`; no TMDB user OAuth session or
account history is used.

## Tool RAG boundary

The two TV tools remain independently useful:

- `tmdb_tv_shows`: artwork, aggregate credits, creators, networks, seasons,
  production metadata, content ratings, filtered discovery, and TMDB lists.
- `trakt_tv_shows`: mood-based ranking, supplied favorite shows,
  related-series signals, and bounded current Trakt lists.

For one combined metadata request, call `action=details` directly with the
title. It resolves the show and bundles its metadata, aggregate credits,
seasons, artwork, videos, recommendations, and similar shows. For posters,
backdrops, and logos together, one `action=images` call with `image_type=all`
returns a balanced bounded set.

## Actions

| Action | Purpose |
|--------|---------|
| `search` | Search TV series by title |
| `details` | Resolve one show and return rich metadata plus bounded aggregate credits, seasons, artwork, content ratings, videos, recommendations, and similar shows |
| `images` | Return ranked posters, backdrops, and/or logos with thumbnail, display, and original CDN URLs |
| `credits` | Return bounded aggregate cast and important crew credits across episodes |
| `videos` | Return bounded public YouTube/Vimeo video metadata, prioritizing official trailers |
| `recommendations`, `similar` | Resolve one show and return TMDB's corresponding series list |
| `trending`, `popular`, `airing_today`, `on_the_air`, `top_rated` | Return bounded public TMDB TV lists |
| `discover` | Filter by included/excluded genre, typical episode runtime, rating/votes, premiere date or future first-air window, origin country/language, sent-show IDs, and supported ordering |

Runtime is a typical episode runtime. Discover results are provider-filtered;
do not reinterpret that value as a total-series duration.

`discover` accepts structured `genres` and `exclude_genres` or a natural
`request`. For example, `science fiction, no anime, next 90 days` resolves to
TMDB's `Sci-Fi & Fantasy` genre, applies `without_genres=16` for Animation,
and bounds `first_air_date` from today through the requested window. Scheduled
workflows can set `require_genres: true` and pass `exclude_show_ids` so an
ambiguous request cannot become an all-genre run and an already emailed series
is skipped.

## Artwork and UI handling

The tool validates TMDB image paths and constructs only bounded
`image.tmdb.org` thumbnail, display, and original URLs from TMDB's current
configuration response. The additive TV structured-result adapter displays
the bounded images without downloading them or modifying Stash or generated
media. A later explicit save can use Jarvis's existing strict image-download
path.

The TV Night workflow may display at most one returned display-size poster and
one backdrop for a title/year match. It does not use `original_url` in Canvas.

## Network, attribution, and trust boundaries

The manifest uses `proxy_policy: prefer`: `LOCAL_PROXY`, then `LOCAL_PROXY2`,
then direct fallback. If neither proxy is configured, the tool starts direct.

Every payload and Web UI result includes TMDB's required notice:

> This product uses the TMDB API but is not endorsed or certified by TMDB.

All metadata and image content is external and untrusted. This version does
not expose TMDB watch-provider data, so it does not infer current subscription
availability from generic series metadata.

## Examples

```text
Use tmdb_tv_shows to find posters, backdrops, and logos for Severance.
```

```text
Use tmdb_tv_shows to show the creators, cast, seasons, network, content rating, and artwork for Dark.
```

```text
Use tmdb_tv_shows to discover highly rated mystery shows with episodes under an hour and at least 500 votes.
```

```text
Use tmdb_tv_shows to discover upcoming science-fiction shows in the next 90 days, no animated or anime series.
```
