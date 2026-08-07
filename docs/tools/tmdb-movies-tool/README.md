# TMDB Movies Tool

`tmdb_movies` is a standalone public movie-discovery, production-metadata, and
artwork tool backed by TMDB. It does not require Trakt and does not read a TMDB
user account. When both movie tools are enabled, workflows may combine their
different evidence: Trakt for its discovery/related-title signals and TMDB for
artwork, credits, collections, release data, and TMDB recommendations.

## Configuration

Put at least one application credential in the active mode env file:

```bash
TMDB_ACCESS_TOKEN="your-api-read-access-token"
# TMDB_API_KEY="your-v3-api-key"
```

The API Read Access Token is preferred and is sent as a Bearer header. If it is
absent, the tool uses `TMDB_API_KEY` as the v3 `api_key` query parameter. The
manifest uses `availability.any_of_env`, so either credential enables the tool.
No TMDB user OAuth session, account history, rating, favorite, or watchlist is
used.

Tracked env examples contain empty placeholders only. Real credentials belong
in ignored `config/cloud.env` or `config/local.env` files.

## Tool RAG boundary

Both `tmdb_movies` and `trakt_movies` work independently. Their descriptions
emphasize different strengths so Tool RAG can rank the best evidence source:

- `tmdb_movies`: posters, backdrops, logos, cast/crew, production details,
  collections, certifications, external IDs, filtered discovery, and TMDB
  recommendations/similar movies.
- `trakt_movies`: movie-night ranking from a mood, supplied favorites,
  related-title signals, and bounded current Trakt lists.

This is not a hard routing exclusion. A direct request for either provider can
use that provider alone, and a workflow may make either tool optional.

## Actions

| Action | Purpose |
|--------|---------|
| `search` | Search movies by translated, original, or alternative title |
| `details` | Resolve one movie and return rich details plus bounded images, credits, videos, release certification, keywords, recommendations, and similar titles |
| `images` | Return ranked poster, backdrop, and/or logo candidates with thumbnail, display, and original CDN URLs |
| `credits` | Return bounded leading cast and important crew credits |
| `videos` | Return bounded public YouTube/Vimeo video metadata, prioritizing official trailers |
| `recommendations`, `similar` | Resolve one movie and return TMDB's corresponding movie list |
| `trending`, `popular`, `now_playing`, `upcoming` | Return bounded public TMDB movie lists |
| `discover` | Filter by genre names, year/date, runtime, vote average/count, and supported TMDB ordering |

`details`, `images`, `credits`, `videos`, `recommendations`, and `similar`
accept either an exact `movie_id` or a `query`. Exact IDs avoid an extra title
resolution request. For a combined cast, director/crew, production,
certification, and artwork request, call `details` directly with the title in
`query`; the action performs its own title resolution and returns the complete
bundle in one tool call.

For constrained recommendations, one `discover` call applies the requested
genre, runtime, rating, vote, date, and sort filters at TMDB. The result includes
an explicit `selection_criteria` guarantee plus a bounded candidate shortlist
for the response model. Individual discover rows do not contain exact runtime
values, but they have already qualified against the provider-side runtime
filter; do not call `details` once per result merely to revalidate that filter.

## Artwork handling

TMDB returns image file paths. The tool queries `/configuration`, accepts only
TMDB's HTTPS `image.tmdb.org/t/p/` base, validates each provider path, and
constructs bounded thumbnail, display, and original URLs using the sizes TMDB
currently advertises.

The Web UI loads only TMDB CDN thumbnails/display images in the additive TMDB
structured-result adapter. `image_type=all` returns a round-robin mix of the
available posters, backdrops, and logos in one tool call. The adapter preserves
that mixed result if a provider redundantly drills into individual image types,
uses artwork-specific aspect ratios, and makes the lead image larger; every
image remains clickable to its original CDN asset.

A search does not download files, create Stash artifacts, or modify
generated-image/video catalogs. A later follow-up may save a selected exact URL
through the existing strict Stash image-download path. Image bytes and all
external metadata remain untrusted content.

## Movie Night workflow

When enabled, `data/workflows/movie_night.json` makes one optional `images`
call for the leading Trakt candidate and requests at most six mixed artwork
results. Canvas may use one display-size poster and one display-size backdrop
when the TMDB title and year match. If TMDB is disabled, unavailable, empty, or
mismatched, the workflow remains runnable and omits the artwork section.

## Network routing

The manifest sets `proxy_policy` to `prefer`. Requests use the shared Jarvis
HTTP client and try `LOCAL_PROXY`, then `LOCAL_PROXY2`, then direct fallback. If
neither proxy is configured, requests start direct. This policy affects only
`tmdb_movies`.

## Attribution and provider boundaries

TMDB requires attribution for its API data and images. Every tool payload and
Web UI result includes:

> This product uses the TMDB API but is not endorsed or certified by TMDB.

The UI links back to [TMDB](https://www.themoviedb.org). Follow TMDB's current
logo, attribution, and licensing requirements for any redistributed or public
deployment.

The first version intentionally omits TMDB watch-provider data. That endpoint
has additional JustWatch attribution requirements and does not return full
provider deep links. Streaming availability can be added later as an explicit,
properly attributed feature rather than being inferred from generic movie
metadata.

## Examples

```text
Use tmdb_movies to find posters and backdrops for Blade Runner 2049.
```

```text
Use tmdb_movies to show the cast, director, runtime, certification, and artwork for Arrival.
```

```text
Use tmdb_movies to discover highly rated science-fiction movies under two hours with at least 500 votes.
```
