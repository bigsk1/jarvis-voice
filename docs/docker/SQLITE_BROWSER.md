# Optional SQLite database browser

Jarvis includes a standalone `sqlitebrowser/` Compose project for inspecting its
SQLite databases through DB Browser for SQLite in a web browser. It is opt-in and
starts separately from Jarvis. The data mount is read-only by default; an operator
can explicitly enable edits with `./start --edit` and restore protection with
`./start --read-only`. `SQLITEBROWSER_READ_ONLY` in its private `.env` selects the
persistent default.

See the [setup and operating guide](../../sqlitebrowser/README.md) and tracked
[example environment](../../sqlitebrowser/.env.example) for configuration, HTTPS
login, native/Docker host paths, Windows/macOS commands, and SQLite WAL snapshots.
The default address is `https://127.0.0.1:8112/`, using a separate login from Jarvis
Web. Its `.env`, application settings, certificates and exports remain ignored by
Git, and it is excluded from the Jarvis Docker image.

Before editing a live database, back it up and stop its Jarvis writers. Editing
bypasses Jarvis validation. Every session on this optional container shares its
mount mode; it does not provide per-user database permissions.
