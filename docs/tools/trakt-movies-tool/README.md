# Trakt Movies Tool

`trakt_movies` adds public movie discovery and metadata to Jarvis using the
Trakt API v2. It is intended for movie-night recommendations, title lookup,
related-film discovery, current public lists, and trailer/video links.

## Configuration

Create a Trakt application and put its **Client ID** in the active mode env:

```bash
TRAKT_API_KEY="your-client-id"
```

The manifest uses the standard `availability.all_of_env` gate. With no Client
ID in the active cloud/local mode, the tool is not loaded and workflows that
require it are not runnable. A Client Secret and OAuth token are not used by
this public-metadata integration. The configured out-of-band redirect URI is
therefore inactive unless a future account-linked feature explicitly adds an
OAuth flow.

## Network routing

The manifest sets `proxy_policy` to `prefer`. Every Trakt API request uses the
shared Jarvis HTTP client, which tries `LOCAL_PROXY`, then `LOCAL_PROXY2`, and
then a direct connection if both configured proxies fail. If neither proxy is
configured, the request starts direct. This is a per-tool policy and does not
change routing for other native or MCP tools.

## Actions

| Action | Purpose |
|--------|---------|
| `recommend` | Blend related movies from up to three favorites with bounded trending, streaming-ranked, and popular candidates; apply mood/genre/runtime constraints and retrieve videos for top options |
| `search` | Search public movie metadata by title or text |
| `details` | Retrieve full public metadata for one Trakt slug or supported external ID |
| `related` | Retrieve movies related to one resolved title |
| `videos` | Retrieve public trailer/video metadata |
| `trending`, `popular`, `anticipated`, `streaming`, `boxoffice` | Retrieve bounded public discovery lists |

`recommend` accepts a natural-language `request`, optional
`reference_titles`, and explicit `genres`, `years`, `runtimes`, or `ratings`.
Runtime, year, and rating constraints are enforced locally after retrieval;
only the stable genre filter is sent to current list endpoints.

## Trust and availability boundaries

- Trakt titles, overviews, links, and video metadata are external, untrusted
  content. Jarvis returns a trust marker and never executes instructions found
  in that content.
- Trakt image URLs are intentionally omitted. Trakt's image guidance requires
  consumers to cache images rather than hotlink them, so the first version does
  not add a new image cache or alter existing generated-media behavior.
- A result appearing in Trakt's streaming list is only a discovery signal. It
  does not identify Max, Paramount+, Prime Video, YouTube, or another provider
  and does not prove current entitlement or regional availability.
- Public metadata does not read a Trakt user's history, ratings, watchlist, or
  personalized recommendations. Those would require a separate, explicit OAuth
  feature.

## Movie Night workflow

`/movie_night <mood, constraints, or favorite movies>` requires
`trakt_movies`, then optionally uses `serpapi_youtube_search` for a visible
trailer rail and `brave_llm_context` for current US provider evidence. Missing
optional tools degrade the run rather than hiding the recipe. The Canvas report
must keep unconfirmed provider availability clearly labeled.

Example:

```text
/movie_night thoughtful mind-bending sci-fi like Inception and Arrival, under two hours, preferably on Max or Prime
```

### Future enhancement: diversified trailer rail

The current optional YouTube step searches only for the leading Trakt
candidate. A future enhancement may add a bounded multi-query option to
`serpapi_youtube_search`, allowing Movie Night to request one or two likely
official trailers for each of the top three movies while still presenting one
grouped tool result. Each title would remain a separate SerpApi search and
therefore consume a separate SerpApi search credit; combining several titles
into one YouTube query would not reliably produce balanced results.
