# Optional stash browser

This is a standalone FileBrowser Quantum v2 beta trial. It runs in its own
Compose project and is not started by Jarvis's main Compose file. Its only
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

HTTP is intentional for this trial. Use a trusted LAN or Tailscale address;
plain HTTP over an untrusted network exposes the login and files. There is no
reverse proxy, Tailscale Serve, or Jarvis integration in this setup. The
read-only Docker bind mount protects stash contents even if an admin tries a
write action in FileBrowser. FileBrowser's own database and cache remain
writable in `data/`.

## Stop or remove

```bash
docker compose down
```

The ignored `data/` directory persists across stops and image updates. Its
database stores FileBrowser accounts and settings, so retain it if you want to
keep the login. Review the [v2 Docker guide](https://filebrowserquantum.com/en/docs/getting-started/docker/)
before updating the beta image or migrating between major versions.
