# Jarvis Craft Tools

Optional editing tools for [PhotoCraft](https://github.com/storytold/photocraft),
[PdfCraft](https://github.com/storytold/pdfcraft),
[LightCraft](https://github.com/storytold/lightcraft),
[FilmCraft](https://github.com/storytold/filmcraft), and
[EffectCraft](https://github.com/storytold/effectcraft). This folder ships our
standalone **Craft Gateway**, repeatable installer, maintenance scripts and an
[agent setup skill](SKILL.md). Jarvis's client lives in `lib/craft_client.py` and
its manifests/entrypoints in `skills/craft_*.tool.json` / `skills/craft_*.py`.

Upstream apps provide CLI/stdio MCP interfaces. **They do not provide our HTTP
API or API key.** Installing this gateway supplies that interface. A browser
landing page, Docker web container and browser login are optional and are not
prerequisites. Browser editing runs on the client; gateway processing runs on
the machine hosting the native apps. Browser projects are not automatically
synchronized with native projects.

## Let an agent perform setup

Point your agent at this repository file and give it the processing host and
chosen Jarvis mode, for example:

> Read `jarvis-craft-tools/SKILL.md` and set up the optional Craft tools. Run the
> apps on my specified Linux host and connect this Jarvis installation in cloud
> mode. Inspect existing apps/services, preserve them, and verify a small edit.

The skill routes to the same installer and troubleshooting instructions below.
It needs authorized host access, such as your existing SSH connection; do not
paste a password, private key or API token into the conversation.

## What the first adapters support

| Jarvis tool | Actions and outputs | Tested upstream version |
| --- | --- | --- |
| `craft_image` | Invert/grayscale, PNG plus editable `.pcraft` | PhotoCraft v0.6.0 |
| `craft_pdf` | Rotate/extract/combine PDFs, render pages and previews | PdfCraft v0.5.0 |
| `craft_photos` | Raster photo exposure development to full-size PNG | LightCraft v0.5.0 |
| `craft_video` | Assemble supplied images/videos with per-clip duration, PNG or MP4 plus project/media archive | FilmCraft v0.5.0 |
| `craft_motion` | Title composition, PNG or MP4 plus native `.ecproj`; optional GPU | EffectCraft v0.7.0 |
| `craft_inspect` | Capabilities, project/job state, collect outputs, request cancellation | Gateway protocol v1 |

These are deliberately bounded adapters, not every upstream command. Sources
are PNG/JPEG/WebP, PDF, and supported MP4/MOV/WebM inputs. RAW development,
interactive masks, arbitrary scripts, external native projects, arbitrary host
paths, and arbitrary MCP calls are not exposed. PhotoCraft projects created by
the gateway can be reused through their Craft reference. Video archives include
media but currently require relinking host paths when opened on another host.
Ordinary conversions, OCR and AI generation retain their existing Jarvis tools.

## Prerequisites

**Processing/gateway host:** Linux x86_64, Python 3.12+, Python venv/pip support, Internet
access to GitHub/PyPI for installation, and enough disk/RAM for the selected
native releases. The installer needs no Rust build or sudo. Release downloads
are SHA256 checked; gateway Python dependencies are pinned and hash checked.
FFmpeg/ffprobe must be installed on the gateway host; movies are inspected and
fully decoded before being published, and project archives have their contents
and CRCs checked. Official release archives may need system libraries; read the native error and
install only missing runtime packages with your package manager. The CLI and
real edit/save/render smoke checks run before activating a downloaded release.

For Debian/Ubuntu, install missing prerequisites with the host administrator:

```bash
sudo apt update
sudo apt install python3-venv python3-pip openssl ffmpeg
```

Check `python3 --version` is at least 3.12. A GPU is optional; its driver and
supported backend must already work on the host. The current EffectCraft GPU
path uses Vulkan on Linux. PhotoCraft's verified headless adapter is CPU.
Processing shares resources with other GPU workloads; one engine job runs at a
time. A gateway host on Windows/macOS is not yet supported. Jarvis clients can
connect from supported native or Docker installations without native Craft
apps or GPU drivers inside Jarvis.

**Jarvis client:** the normal Jarvis environment and a route to the gateway.
“Cloud”/“local” refers to the selected Jarvis ENV, not the gateway's location.
A cloud server cannot reach a private LAN IP without a route/VPN. Keep this a
trusted self-hosted service; this first release has one shared API principal,
not a public multi-tenant editing service.

## Setup: apps and Jarvis on the same native Linux host

1. Clone Jarvis Voice and enter the checkout. Run the standalone installer:

   ```bash
   ./jarvis-craft-tools/setup.sh --start
   ```

   This installs all five locked releases under `~/apps`, installs the gateway
   under `~/apps/craft-gateway`, generates a private key, and starts a systemd
   **user** service on `http://127.0.0.1:19444`. Port 19444 is configurable; check
   it is free with `ss -ltn` first. Nothing starts through ordinary Jarvis setup.
   To install just two apps, add `--apps photocraft pdfcraft`.

2. Configure exactly the Jarvis mode you want, without printing the key:

   ```bash
   python3 jarvis-craft-tools/scripts/configure_jarvis.py \
     --settings "$HOME/apps/craft-gateway/jarvis-client.env" --mode cloud
   ```

   Use `--mode local` for local mode, or run twice to opt both modes in. The
   selected ENV must already exist from ordinary Jarvis setup. All other ENV
   settings are preserved. These private files are not committed.

3. Verify connectivity and capabilities:

   ```bash
   python3 jarvis-craft-tools/scripts/probe.py \
     --settings "$HOME/apps/craft-gateway/jarvis-client.env"
   ```

4. Reload/restart Jarvis normally, then synchronize the tools for that mode:

   ```bash
   source "$HOME/jarvis-venv/bin/activate"
   ./bin/sync-tools.py cloud
   ```

   Use `local` for local mode. This sync contacts your configured embedding
   provider and uses Jarvis's legacy tool-sync environment by design. Review
   your selected tool profile/Web block settings if a tool is still hidden.

5. Ask Jarvis to inspect Craft capabilities, then try a small image or PDF from
   Stash. For example: “Use Craft to invert this image,” or “Rotate page 1 of
   this PDF 90 degrees.” Ask for MP4 explicitly for video/title delivery.

## Setup: apps on another Linux host

Run the installer **on the processing host**, using its own clone of this repo
or a copy of this folder. Nothing requires the full Jarvis runtime there.

For a folder-only transfer, keep its contents together (including `scripts/`,
`craft_gateway/`, `pyproject.toml`, and `requirements.lock.txt`). For example:

```bash
scp -r jarvis-craft-tools user@processing-host:~/
```

The processing-host commands below run **inside the `jarvis-craft-tools/`
source folder**, whether copied separately or included in a clone. Installer
state, downloads and generated credentials go to the selected
`--root`/`--apps-root`, not into the source folder. The later client commands run
from the **Jarvis Voice checkout root on the Jarvis client**.

1. **On the processing host**, enter the copied folder, choose a free
   unprivileged port and replace `YOUR_LAN_IP` with its intended interface IP:

   ```bash
   cd "$HOME/jarvis-craft-tools"
   ./setup.sh --bind YOUR_LAN_IP --tls-host YOUR_LAN_IP \
     --port 19444 --start
   ```

   If this host has a full clone instead, replace the `cd` line with
   `cd /path/to/jarvis-voice/jarvis-craft-tools`, using its actual checkout
   location. The `./setup.sh` command is the same in either source folder.

   `--tls-host` generates a private CA and a server certificate with the correct
   IP/DNS subject alternative name. Supply a bare IP or DNS name, not a URL or
   port. DNS access requires using that name in the Jarvis URL. Non-loopback
   plaintext listeners are rejected. The installer does not open firewalls or
   change routers; permit only intended clients in your host/network policy.

2. Securely copy `~/apps/craft-gateway/jarvis-client.env` to a private file on the
   Jarvis client, and **only** `~/apps/craft-gateway/tls/ca.crt` as the public CA.
   Use your normal authorized SSH/SCP connection. Never copy `ca.key`,
   `server.key`, or the entire TLS/private directory. Protect the settings file
   with `chmod 600`; do not paste its key into an agent conversation.

3. **On the Jarvis client, from its Jarvis Voice checkout root**, configure
   the connection using client-side paths:

   ```bash
   python3 jarvis-craft-tools/scripts/configure_jarvis.py \
     --settings /private/path/craft-client.env --mode cloud \
     --api-url https://YOUR_LAN_IP:19444/craft-api/v1 \
     --ca-bundle /client/path/craft-ca.crt
   ```

4. **On the Jarvis client, still from its checkout root**, verify connectivity
   with the same settings and client-side CA:

   ```bash
   python3 jarvis-craft-tools/scripts/probe.py \
     --settings /private/path/craft-client.env \
     --api-url https://YOUR_LAN_IP:19444/craft-api/v1 \
     --ca-bundle /client/path/craft-ca.crt
   ```

   Then follow the reload/tool-sync/test steps above from this client checkout.
   A normally trusted HTTPS certificate needs no `CRAFT_CA_BUNDLE`; leave that
   value blank and omit `--ca-bundle` from the helper commands instead.

The API key is generated by **our installer**, not obtained from the upstream
projects. Rerunning setup preserves it and the existing CA. Browser credentials
are unrelated. Set private mode ENV values directly if you prefer manual setup:

```dotenv
CRAFT_API_URL="https://your-craft-host:19444/craft-api/v1"
CRAFT_API_KEY="your-generated-gateway-key"
CRAFT_CA_BUNDLE="/client/path/to/craft-ca.crt"
# CRAFT_WAIT_SECONDS=90
```

URL and key blank/missing disables all Craft tools. Configuration is independent
between modes. No network probing occurs during manifest availability checks;
a missing app/unsupported version is rejected by the specific tool preflight.

## Existing native installations and optional HTTPS proxy

Use `--skip-app-install --apps-root /your/apps` to keep existing managed app
releases. Expected binary layout is `APP/current/bin/APP-cli`; managed release
metadata supplies the tested version. For a different layout, set a `binaries`
map in private `gateway.json`, mapping app names to executable paths. Unmanaged
or newer versions remain disabled unless you explicitly set
`allow_untested_versions: true` after testing them; the API reports that version
status. Do not claim an untested version is supported.

If you already have an HTTPS reverse proxy, avoid generating another CA. Run
this example **from the full Jarvis checkout root on the processing host**:

```bash
./jarvis-craft-tools/setup.sh --skip-app-install \
  --unix-socket "$HOME/apps/craft-gateway/run/api.sock" --start
```

For a folder-only copy, enter that folder and use `./setup.sh` with the same
arguments instead of `./jarvis-craft-tools/setup.sh`.

Proxy `/craft-api/v1/*` **without stripping the prefix** to that Unix socket.
The proxy must have access to the socket directory and socket; when the proxy
runs in Docker, mount the **directory**, so socket recreation on restart works.
Terminate TLS at the proxy. The API itself verifies its dedicated bearer key
for every route. Browser Basic authentication can remain on browser routes;
do not put it in front of the API as a second, undocumented login requirement.
Use a separate API route, preserve other routes, and validate before reloading.
A Caddy example for a site block is:

```caddyfile
handle /craft-api/v1/* {
    reverse_proxy unix//run/craft-api/api.sock
}
```

Ensure existing site-wide Basic auth is moved into the browser-route branch
rather than covering this API. A gateway or proxy URL must end in
`/craft-api/v1`; pointing at a browser app or stdio MCP endpoint will not work.

## Jarvis in Docker

Keep the gateway external to the Jarvis image. Use its reachable **HTTPS** LAN
or private-network URL, even if it is on the same physical host. Container
`127.0.0.1` points to the container. You do not need Craft binaries in the image.
Mount your public CA read-only into the Jarvis container and set
`CRAFT_CA_BUNDLE` to that container-side path, for example `/certs/craft-ca.crt`.
Add the volume to the existing Compose service rather than replacing its other
mounts. Verify the connection from inside that running container. The gateway
uses one worker process; do not horizontally scale Uvicorn against one state
folder. Jarvis's optional background task runner currently supports Linux;
macOS native clients retain the foreground path.

## Jobs, follow-up edits and delivery

All inputs upload into server-owned project folders. Input filenames cannot
be paths, native project uploads are rejected, and outputs get artifact IDs.
Original files are never overwritten. Projects serialize their writers and use
revision checks. Job acceptance and idempotency IDs are stored in SQLite before
execution. A lost submit response is looked up by request ID instead of being
resubmitted. After restarting the gateway, interrupted jobs are reported for
inspection; they are not replayed.

Jarvis waits up to `CRAFT_WAIT_SECONDS` (90 by default, capped at 110) in a
foreground call. If the job continues, it returns an honest running receipt
with project/job IDs. Use `craft_inspect` action `job`, then `collect` when it
succeeds. With Jarvis background tasks enabled and the Craft tool selected,
the client observes up to 1200 seconds and delivers completed files through the
existing background system. Long queue waits can still require manual collection.
Stopping the local observer does not cancel a remote job; `craft_inspect` action
`cancel` requests gateway cancellation and reports its state. Running cancellation
is only terminal after the engine process group has stopped.

Completed outputs are checksum verified and saved to the configured canonical
Stash, including supporting project files, with links and follow-up metadata.
Reuse `craft://PROJECT/ARTIFACT` sources with the matching `project_id` to avoid
uploading again, or use a Stash output as a new source. Adapter scope still
applies: a PhotoCraft editable project can be reopened, while title creation
currently creates a fresh composition per request. Do not imply a full live
browser/native editing session or automatic project synchronization.

Default limits: 50 MiB per input/output artifact, 512 MiB scratch per job,
4 GiB gateway workspace storage, eight active/queued jobs, 900 seconds per
engine job, and one active engine job. The installed user service also limits the API and its
children to 6 GiB RAM, two CPU cores of quota and 256 tasks; GPU VRAM is not capped.
Configure private `gateway.json` to tune
host limits; Jarvis downloads remain capped at 50 MiB per artifact. Workspace
quota is conservative and leaves room for queued jobs. This gateway uses typed
arguments and restricted engine environments, **not an OS filesystem sandbox**.
The service account can read files accessible to that account. Use only trusted
clients and releases; no arbitrary scripts or raw upstream MCP passthrough.

### Retention and current follow-up boundaries

The gateway retains inputs, outputs and native projects until explicit operator
cleanup; they count toward its disk quota. Jarvis's downloaded Stash copies use
project/source-artifact retention (normally 120 days, subject to existing
reference protection). They are not automatically permanent. If a Stash copy
expires, `craft_inspect` action `collect` can download a successful job again
while its gateway artifacts remain. Back up gateway state/projects for durable
retention; Stash retention and gateway retention are separate.

Only the PhotoCraft adapter currently reopens its gateway-produced native
project. EffectCraft title creation creates a new composition per call;
LightCraft development exports a PNG without a persistent library; FilmCraft
creates a new timeline and returns a project/media archive with host paths to
relink. Reusing a `project_id` organizes related jobs and serializes writers;
it does not turn these three adapters into a persistent editing session.
The tested cross-app handoff is EffectCraft MP4 to FilmCraft. Importing a
PhotoCraft graphic into an existing EffectCraft composition is future adapter
work. Native engine capabilities do not imply that the gateway exposes them.

### Try it in Jarvis Web

For a chat image upload, choose **Analyze** and send a message first. After a
successful analysis, Jarvis saves an image copy to Stash for follow-up tools.
Cancelling the image-action dialog does not save the image to Stash. The
**Image** and **Video** choices route to AI generation tools, rather than Craft.
Chat image uploads are resized to at most 1024 pixels and converted to JPEG;
use an original file already in Stash for full-resolution edits.

Try these in the same conversation, using an explicit `stash://` reference if
the intended source is ambiguous:

- "Use PhotoCraft to invert the colors of the uploaded image and save the PNG
  and editable project." Then: "Make that saved PhotoCraft project grayscale."
- "Use LightCraft to brighten the uploaded image by 0.6 stops and export PNG."
- "Use FilmCraft to make a two-second clip from the uploaded image at 320 by
  180 pixels, 12 fps. Export MP4 and the project archive."
- "Use EffectCraft to make a two-second animated title saying Craft Test,
  320 by 180 pixels, 12 fps, with GPU rendering. Export MP4 and the project."
- After attaching a PDF: "Use PdfCraft to rotate only page 1 by 90 degrees,
  save the PDF, and show its preview."

Expect a successful job and saved Stash outputs, or an honest running receipt
with a job ID. For a running receipt, ask Jarvis to inspect and collect that
job; avoid repeating the editing request while its outcome is unknown.

## Service operation and maintenance

```bash
systemctl --user status jarvis-craft-gateway
journalctl --user -u jarvis-craft-gateway -n 80 --no-pager
systemctl --user stop jarvis-craft-gateway
systemctl --user start jarvis-craft-gateway
```

`--start` enables a user service, which may only start after login. Check boot
persistence with `loginctl show-user "$USER" -p Linger`. To run while logged out,
an administrator may need to enable linger for your user. Setup does not change
that system-wide setting automatically. On a host without a user service
manager, omit `--start` and run the foreground command printed by the installer
under your normal process supervisor. It defaults to loopback HTTP.

Gateway updates: pull the reviewed repo changes, stop the gateway, rerun the
same setup command/options with `--skip-app-install`, then start/probe it. Code
snapshots are retained under `releases`; state and credentials stay outside the
code snapshots. Do not delete workspaces to update. `setup.sh` is idempotent for
an unchanged release/credential identity.

Native app updates: inspect active jobs, stop the gateway, back up its `state`
and any native projects, then run the release manager from this checkout:

```bash
python3 jarvis-craft-tools/scripts/manage_apps.py status --root "$HOME/apps"
python3 jarvis-craft-tools/scripts/manage_apps.py update photocraft \
  --root "$HOME/apps" --version v0.6.0
python3 jarvis-craft-tools/scripts/manage_apps.py check photocraft --root "$HOME/apps"
```

Omit `--version` to request upstream latest, but newer alpha releases may be
incompatible and will be blocked by the gateway until tested/adapted. Existing
managed releases and update smoke checks are retained. Use `rollback APP
--version TAG --root PATH` for an installed managed release. A binary rollback
does not undo project-format or library migrations. On a host with the earlier
optional browser updater, the release manager also tries its matching web sync;
a successful native update is not reversed if that browser sync fails.

Gateway credentials: stop the service, generate a new private `api_key` in
`gateway.json` (for example with `secrets.token_urlsafe(48)` in a private script),
rerun setup to refresh the private client settings, update opted-in Jarvis ENV
files securely, and start the gateway. Never reuse browser passwords as API keys.
The generated server certificate lasts one year. Setup checks whether it remains
valid for at least 30 days; rerunning setup with the original `--tls-host` renews an expiring server
certificate using the existing CA. Do not rotate the CA silently;
clients would need a new trusted public certificate.

Workspace cleanup is explicit in this first release. Stop the gateway and back
up state before removing unused projects; metadata and on-disk projects must be
kept together. The gateway stops admitting jobs when its quota is exhausted.
There is no automatic deletion of editable projects.

## Troubleshooting

| Symptom | Check and remedy |
| --- | --- |
| `python3` older than 3.12 | Install a supported interpreter on the processing host; use it to run `scripts/setup_gateway.py`. |
| `ensurepip`/venv missing | Install the matching `python3-venv` package. Gateway dependencies are separate from Jarvis's venv. |
| GitHub download/rate-limit/checksum failure | Check connectivity and release availability. Leave a mismatched cached package for inspection; do not skip checksum validation. |
| Native smoke check fails | Inspect the reported CLI/workflow error and missing shared libraries; previous selected release remains active. |
| `address already in use` / connection refused | Check `ss -ltn`, service status and logs; select a free `--port`. Do not stop unrelated services. |
| No systemd user manager | Omit `--start`; run the installed foreground command under your existing supervisor. |
| Service stops after logout / not available after reboot | Check user linger and user-service enablement. |
| HTTP 401 | Gateway API key missing/wrong. Browser password is a different credential. Check selected mode and key rotation. |
| Certificate verification failure | Match URL host to certificate SAN; copy public CA to the client and set its client-side/mounted path. Browser trust does not necessarily configure Python requests. |
| Browser login HTML or redirect instead of JSON | Wrong URL or site-wide Basic auth intercepting API. Configure a separate bearer-authenticated proxy route. |
| Remote URL rejected as plaintext | Use HTTPS for remote/Docker connections; loopback HTTP is only for a same-host native client. |
| Partial app installation / untested version | Inspect `craft_inspect` capabilities; install the locked release or explicitly verify a newer adapter. |
| Tools missing from Jarvis | URL/key must be nonblank in the selected mode; review profile/Web blocks, reload and sync Tool RAG for that mode. |
| Foreground returns a running job | Normal for long work: inspect/collect by the saved job ID. Enable and select Craft background tools for automatic late results on Linux. |
| Lost reply / interrupted job | Look up `job_id` or `request_id`, or use `craft_inspect` action `jobs` if the observer stopped before returning IDs; inspect before any new submission. No automatic replay occurs. |
| HTTP 409 / project revision conflict | Another writer/job owns that project. Inspect its current revision and wait or choose a new project. |
| HTTP 413 / disk quota | Reduce input/output size or back up and maintain unused workspaces; do not delete user projects blindly. |
| GPU failure | Retry a new explicitly requested CPU job after inspecting the failed one; check host driver/Vulkan support. GPU defaults off. |
| Bare FilmCraft project cannot find media | Extract its project archive and relink the included media paths on that host. |

## Development and verification

From the Jarvis checkout:

```bash
.venv/bin/python -m pytest jarvis-craft-tools/tests tests/test_craft_tools.py -q
python3 /path/to/skill-creator/scripts/quick_validate.py jarvis-craft-tools
```

`jarvis-craft-tools` has no effect on ordinary Jarvis setup, requirements, mode
switching or database migrations. The gateway adds its own isolated dependencies,
SQLite job store and workspace on the selected processing host. Public defaults
contain no private hostnames, API keys or deployment certificates.

Review follow-up verification: the tests additionally cover confirmed 409
rejections and mismatched recovery, wrong-CA TLS failure, lost polling with job
identity retained, native diagnostic reporting, corrupt movies/archives, and
PDF preview/running receipts through the shipped Web renderer. A real Jarvis
Docker client reaching this gateway has not been verified; its documented
certificate mount and network setup remain a deployment check.

A live remote title render was also observed running, then its client polling
transport was deliberately disconnected. A fresh client recovered that same
request/job, collected the completed outputs and did not submit a second job.
