# Trakt Account Tool

`trakt_account` is an optional, authenticated, **read-only** companion to the
public `trakt_movies` and `trakt_tv_shows` tools. It can read personalized
recommendations, watchlist, history, ratings, favorites, personal lists, smart
lists, and up-next progress. It does not add, remove, rate, mark watched, create
lists, or otherwise change a Trakt account.

## Setup

Create or open a Trakt API application and configure the active Jarvis mode:

```dotenv
TRAKT_API_KEY="your_client_id"
TRAKT_CLIENT_SECRET="your_client_secret"
TRAKT_REDIRECT_URI="urn:ietf:wg:oauth:2.0:oob"
```

The redirect URI must exactly match the value registered with Trakt. The OOB
URI above is appropriate for Jarvis's device authorization flow. Then authorize
the account interactively:

```bash
./bin/trakt-auth --mode cloud
# or
./bin/trakt-auth --mode local
```

Open the printed Trakt URL, enter the device code, and approve access. Jarvis
stores the resulting token cache at `data/.trakt_oauth.json`. The file and its
refresh lock are gitignored; the cache is written atomically with mode `0600`
on POSIX systems. The Client Secret remains only in the active ENV file.

Trakt access tokens expire after seven days. Jarvis refreshes them before
expiry and serializes refreshes because Trakt refresh tokens are single-use.
If authorization is revoked or the Client ID changes, run `trakt-auth` again.

## Actions

- `status`: confirm authorization and return safe account capability metadata.
- `movie_recommendations`, `show_recommendations`: authenticated Trakt
  recommendations with optional genre, year, runtime, and rating filters.
- `movie_night_context`, `tv_night_context`: infer bounded recommendation
  filters from a natural-language viewing request and, when `ignore_watched` is
  true, compare both public-workflow and account candidates against the full
  bounded Trakt watched sync by stable media identity.
- `watchlist`, `history`, `ratings`, `favorites`: paginated account reads.
- `personal_lists`, `personal_list_items`: read owned list definitions/items.
- `smart_lists`, `smart_list_items`: read smart-list definitions/items.
- `up_next`: read progress-based next episodes.

Account-derived results are marked `account_data: true`, `oauth_used: true`,
and `read_only: true`. Returned titles, descriptions, URLs, and notes are still
treated as untrusted external content.

Night-workflow watched filtering reads `/sync/watched/movies` or
`/sync/watched/shows` in pages of 100, up to 20 pages. Only identity keys and
aggregate counts are retained; raw watched rows, timestamps, seasons, and
episode history are not returned to the workflow or response model. If Trakt
reports more than the bounded page limit, the optional account step fails
closed instead of claiming a partial watched filter, and the workflow continues
with its public-only fallback.

## Public access, OAuth, and VIP

These are separate capability layers:

- `TRAKT_API_KEY` alone enables the two public discovery tools.
- A Client Secret plus OAuth cache enables `trakt_account`.
- Trakt VIP may unlock provider-defined endpoints or higher limits; it is not a
  second authentication method.

When Trakt returns `426`, Jarvis reports that the endpoint requires VIP. When
it returns `420`, Jarvis reports a VIP Enhanced account limit. Safe upgrade and
limit headers may be returned, but OAuth tokens and secrets are never included.

## Docker and multiple modes

Mount or persist `data/.trakt_oauth.json` anywhere the Jarvis process can read
it. The cache is bound to a Client ID fingerprint, so Cloud and Local modes can
share it only when both use the same Trakt application credentials. Otherwise,
authorize again after switching credentials.
