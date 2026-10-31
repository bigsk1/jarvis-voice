# Optional stash browser

This is a standalone FileBrowser Quantum v2 stable installation. It runs in
its own Compose project and is not started by Jarvis's main Compose file. Its only
content mount is the Jarvis stash, mounted read-only at `/srv`. FileBrowser's
database and preview cache live in the ignored `data/` directory here.

## Start

From this directory, copy the public example to `.env`, then set
`FILEBROWSER_ADMIN_PASSWORD` to a unique password of at least 12 characters.
Set `FILEBROWSER_BIND_IP` to the host's Tailscale or trusted LAN address to
reach it from another device. The example binds to loopback until you change
it. `FILEBROWSER_PORT` defaults to `8111`. Create the `data` directory, then
start the service:

```bash
cp -n .env.example .env
# Edit .env to set the password and, if needed, the bind IP.
mkdir -p data
docker compose up -d
docker compose ps
```

Visit `http://<FILEBROWSER_BIND_IP>:8111/` and sign in as `admin` with the
password from `.env`. The first page should list `space_*` folders. Preview
or download an artifact to check the rendering. This address is separate from
Jarvis's `/stash/` viewer and uses FileBrowser's own login; Jarvis Web cookies
do not authenticate this service.

The default host source is `../data/stash`. If Jarvis uses a custom `STASH_DIR`
or `JARVIS_OVERRIDE_STASH_DIR`, set `FILEBROWSER_STASH_PATH` in `.env` to its
actual **host** path before starting. The bind mount refuses to create a
missing source directory, so a wrong path cannot appear as an empty stash.

HTTP is intentional for this optional service. Use a trusted LAN or Tailscale address;
plain HTTP over an untrusted network exposes the login and files. There is no
reverse proxy, Tailscale Serve, or Jarvis integration in this setup. The
read-only Docker bind mount protects stash contents even if an admin tries a
write action in FileBrowser. FileBrowser's own database and cache remain
writable in `data/`.

## Analytics

Deployment analytics are opt-in and should stay disabled for this setup. In
**Settings → System Admin**, leave the analytics toggle off. FileBrowser stores
this choice in its database, separately from `config.yaml`; there is no YAML or
environment setting for analytics in this release.

With a FileBrowser admin session, `GET /api/settings/analytics` should return
`enabled: false`. To explicitly persist that choice, send
`PUT /api/settings/analytics` with `{"enabled": false}`. It takes effect immediately
without a restart. `publishSupported: true` describes the image's capability,
not whether analytics are enabled.

## Update

The Compose file pins the full `gtstef/filebrowser:2.0.2-stable` image, which
includes FFmpeg for video previews. This release fixes the media-processing hang
in 2.0.8/2.0.9-beta and WebP thumbnail generation. See the
[release notes](https://github.com/gtsteffaniak/filebrowser/releases/tag/v2.0.2-stable).

For a future update, review the release notes, save the current `compose.yaml`,
and record the running image tag or ID for rollback. Select an explicit new tag
in `compose.yaml`, then pull it before stopping the running service:

```bash
docker compose pull filebrowser
docker compose stop filebrowser
# Back up data/, config.yaml, and .env outside data/, with the previous compose.yaml.
docker compose up -d filebrowser
docker compose ps
```

Keep the backup private: it contains account data and credentials. SQLite schema
changes run automatically on startup. Retain the previous image and the backup
until login, read-only Stash access, image/video thumbnails, and video playback
work. To roll back, stop the service, restore its previous database/settings and
image tag, then start it again. Changing only the image can leave an older build
reading a migrated database. Jarvis services do not need to restart.

## Stop or remove

```bash
docker compose down
```

The ignored `data/` directory persists across stops and image updates. Its
database stores FileBrowser accounts and settings, so retain it if you want to
keep the login. Review the [v2 Docker guide](https://filebrowserquantum.com/en/docs/getting-started/docker/)
before migrating between major versions.
