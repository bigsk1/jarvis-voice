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
| `craft_image` | Text overlays and revisions, crop/resize/rotate, image placement, invert/grayscale; PNG plus editable `.pcraft` and layer inspection | PhotoCraft v0.6.0 |
| `craft_pdf` | Rotate/extract/combine PDFs, render pages and previews | PdfCraft v0.5.0 |
| `craft_photos` | Raster photo exposure development to full-size PNG | LightCraft v0.5.0 |
| `craft_video` | Trim source ranges, assemble clips, fitted titles/timed captions over footage, native text revisions; MP4/preview plus editable timeline and media archive | FilmCraft v0.5.0 |
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
applies: image and video native projects can be reopened for supported edits, while title creation
currently creates a fresh composition per request. Do not imply a full live
browser/native editing session or automatic project synchronization.

`craft://PROJECT/ARTIFACT` is a gateway artifact identifier. The gateway
resolves it inside its configured `state_dir/projects/PROJECT/` workspace,
usually beneath a job subfolder; it is independent of a client's filesystem
paths. `stash://SPACE/FILE` identifies a copy on the Jarvis host. A confirmed
Web Craft upload is first preserved in Jarvis upload storage; sending the
turn saves it to Stash, and the tool uploads a processing copy to the gateway.
Successful exports, native projects and inspection files are downloaded back
to Jarvis Stash. Both references can therefore point to copies of the same
artifact on different hosts. `editable_project_ref` selects the gateway's
native project for subsequent edits; the result's `file_path` names its
downloaded Jarvis copy. The modal hides Craft when `craft_image` is disabled,
blocked, or missing its gateway configuration in the selected mode.

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

PhotoCraft reopens gateway-produced native projects using the returned
`editable_project_ref`. Follow-up results include `document` with layer IDs,
names, text and bounds. Supply `project_revision` from the prior result to
reject a stale write. Use the native project reference rather than the PNG to
preserve editable text and layers. Native projects uploaded from another
machine remain prohibited; the gateway trusts only its own produced projects.

### Image editing and follow-ups

Use `craft_image` action `edit` with `sources` and 1..16 ordered `edits`:

```json
{
  "action": "edit",
  "sources": ["stash://YOUR_SPACE/YOUR_FILE"],
  "edits": [
    {"action": "resize", "width": 800, "height": 450},
    {"action": "text", "name": "Caption", "text": "WHEN THE UPLOAD CANCELS", "placement": "top", "font_size": 64}
  ]
}
```

Supported image edits are `text`, `update_text`, `crop`, `resize`, `rotate`
(90/180/270 degrees clockwise), and `overlay`. Caption placement is `top`,
`center` or `bottom`; alignment is `left`, `center` or `right`. White text and
black outline are defaults; colors and outline width are configurable. Font
size is a maximum in pixels; the native layout is checked and reduced until
all words fit. Captions that cannot fit at a readable size fail instead of
publishing a partial caption. No AI image generation runs for these edits.

For a revision, use the prior result's `editable_project_ref` as the first
source and target the returned text-layer ID or exact unique name:

```json
{
  "action": "edit",
  "editable_project_ref": "craft://YOUR_PROJECT/YOUR_PROJECT_ARTIFACT",
  "project_revision": 1,
  "edits": [{"action": "update_text", "layer": "Caption", "text": "NEW WORDS", "placement": "bottom"}]
}
```

For revisions, pass `editable_project_ref` directly and omit `sources`. The
exported `stash_ref` is flattened media for delivery; it cannot select an
editable text layer. Flat-image/movie `update_text` requests are rejected
before upload or project creation. An echoed default `name: "Caption"` on an
image revision, or an echoed existing layer name, is accepted and ignored;
existing layer names are preserved. For size/placement changes, omit `text`
to keep the words. Font size uses full source-image pixels, rather than the
resized preview. Reuse the revision from the last successful result: rejected
calls do not advance it. Conflicts return the current revision for inspection.
Wait for running jobs to complete and collect their native project before
revising. The single-writer rule rejects a second edit while one is active;
inspect the job instead of replaying it.

The client infers the project ID from a Craft reference. Changes create a new
saved project artifact and increment the gateway revision; earlier artifacts
remain intact. Additional image sources are used by `overlay` through their
zero-based `source` index (1 is the second source), with an `x`, `y`, `width`,
`height` placement rectangle. Place crop/resize/rotation edits before captions;
a final edit that clips text is rejected. Originals are never overwritten.

### Video cuts, overlays and revisions

Use `craft_video` action `edit`. A new cut accepts ordered `clips` with
zero-based source index and source `start`/`end` seconds. Source audio is
retained. Example: keep seconds 5 through 20, then put a title over the cut:

```json
{
  "action": "edit",
  "sources": ["stash://YOUR_SPACE/YOUR_VIDEO"],
  "clips": [{"source": 0, "start": 5, "end": 20}],
  "video_edits": [{"action": "title", "text": "My edited video", "placement": "top"}],
  "output": "mp4"
}
```

`video_edits` actions `title` and `caption` add editable graphic text ON the
footage. Their `start` and `duration` use seconds in the **edited timeline**,
not source timestamps. Captions default to the bottom, titles to the top;
text fits into a safe paragraph box. Overlays must lie within the footage;
clipped or overlapping text is rejected. Supplied timed captions use native
graphic text layers: this is not automatic transcription, SRT import/export,
or a native subtitle-track adapter.

The result includes `editable_project_ref` for `.fcproj`, a `document` with
source ranges and overlay `clip`/`layer` IDs, and a project/media ZIP. To revise
text, supply that project reference as the sole source, keep `clips` omitted,
and use `video_edits` with `action: "update_text"`, its `clip` and `layer`, and
optional new `text`. Omit `text` to keep the words while changing `placement`,
font size or color. Omit timing fields; echoed defaults `start: 0` and
`duration: null` also retain the saved timing, even when the caption starts
later than zero. You may instead copy the selected overlay's actual `start`
and `duration` from `document.overlays`. The gateway compares them with the
saved clip before changing its text or style; different timing values are
rejected. Clip timing, footage and
linked audio remain in the existing timeline. New source cuts use media
sources and `clips`; trimming an existing native clip in place, arbitrary
compositing, grading and audio mixing remain future adapters.

New video cuts automatically fit oversized sources within 1920x1080 while
preserving aspect ratio, with even default dimensions for MP4. One explicit
dimension derives the other for new cuts and reopened timelines. The default frame rate preserves
the source rate up to 60fps. Reopened timelines keep their settings unless
explicitly changed. A frame-size revision refits and centers the retained
source clips and reflows existing text boxes, preserving IDs, words and timing.
Explicit supported dimensions/fps override defaults; `assemble`
retains its existing 640x360/24fps defaults. Limits are 1920x1080, 1..60fps,
120 seconds of output and the gateway's transfer/disk quotas. Longer source
videos can provide a short range. PNG output is a preview; request `mp4` for
a movie. The ZIP includes every referenced media file, even on a follow-up;
opening it elsewhere still requires relinking its saved host paths. External
native project uploads remain prohibited.

### Try it in Jarvis Web

Attach an image, choose **Edit with Craft**, enter the edit instructions and
send. **Save to Stash** saves it for later requests when you send, without
vision analysis or forced generation. Multiple image sources can be used for
image/logo overlays. Craft must be configured for actual edits; saving to
Stash does not require the gateway. Cancelling the dialog does not save it.

Ordinary uploads create only the reduced JPEG preview. Analyze and AI
generation retain their existing preview behavior, including phone photos
above 32 megapixels (subject to the existing 30 MB and Pillow decode limits).
Choosing Craft/Stash prepares a full-resolution, orientation-normalized static
PNG source, including transparency, from the selected original. Only this
explicit full-source path has the 32 megapixel limit. If it is too large, the
modal keeps the preview and original selection so you can choose Analyze or
resize the original. Older uploads without a saved source fall back to their
existing preview. Craft/Stash source copies use normal project retention, 120
days; Analyze and generation uploads retain their seven-day copies.

Upload responses distinguish preview `width`/`height` from original
`source_width`/`source_height` and report whether `source_preserved` is true.
Stashed edit context reports the actual source and preview dimensions. Crop
and overlay coordinates use source pixels; do not guess them from the 1024px
preview. The attachment tooltip shows preserved source dimensions.

Try: "Put WHEN THE UPLOAD CANCELS at the top of this photo as a meme."
Then: "Change the existing caption to BUT THE PHOTO IS STILL HERE and move it
to the bottom." Jarvis receives the saved project reference and layer metadata
for the next turn. The browser editors still have separate sessions; export
native files explicitly to open them there.

EffectCraft standalone titles now use native text bounds to fit the complete
caption inside the frame, with a fade at the end. Use PhotoCraft for text on a
photo; a standalone title card is not a replacement for a source-image edit.

## Craft meme workflow and video ideas

The shared [`craft_meme_maker`](../data/workflows/craft_meme_maker.json)
workflow is a small example built from existing tools:

1. Upload **one photo** in Jarvis Web and choose **Save to Stash**. This keeps
   the full-resolution source and lets the workflow do its own vision pass.
2. Select **Craft Meme Maker**, or type `/craft_meme_maker`.
3. Optionally add a theme or exact caption, then send.

```text
/craft_meme_maker
/craft_meme_maker Make this about Monday meetings
/craft_meme_maker Use the exact caption: TECH SUPPORT SAID TO SIT TIGHT
```

The first form needs no extra request: vision looks at the photo and invents
one short joke. The workflow passes that caption to `craft_image`, which adds
white, black-outlined text at the bottom and fits it inside the image. The
photo is preserved; this recipe does not repaint the subject. For example, a
dog sitting beside a printer might become “TECH SUPPORT SAID TO SIT TIGHT.”
Caption wording is model-generated, including when the model is asked to copy
supplied words. A later edit can revise the returned text layer.

Use **Save to Stash** for this recipe rather than **Edit with Craft**: the
latter adds a separate direct-tool hint. The workflow already selects Craft.
If several photos are attached, this recipe uses the first Stash reference;
attach one to make the choice explicit. Existing files also work:
`/craft_meme_maker stash://YOUR_SPACE/YOUR_IMAGE Make this about coffee`.

The core steps are `analyze_image` → `craft_image`, followed by optional Canvas
publication. No image generator, extra conversion, helper-model round trip, or
new dependency is needed. The selected mode needs working vision and a
configured PhotoCraft gateway. Standard Craft results carry the PNG, editable
project and layer metadata for follow-up edits. The normal Web media preview
shows the returned image. When Canvas is available, a completed image also
gets a `Memes/` page and links in the final response.
If Canvas is unavailable or fails, the Craft files remain in the tool result.
Workflows use foreground tool execution. If Craft is still running when its
wait budget ends, completion text reports that state; inspect/collect the
existing job instead of running the workflow again. Canvas publication requires
both a successful render state and an actual image reference; pending jobs
never publish a placeholder page or start a second render.

### Dramatic meme trailer

The [`craft_meme_trailer`](../data/workflows/craft_meme_trailer.json) recipe
turns one photo into a silent, 10-second MP4. Upload with **Save to Stash**, then
select **Craft Meme Trailer** or use:

```text
/craft_meme_trailer
/craft_meme_trailer Make it about a dog running the office
/craft_meme_trailer Use the exact punchline: THIS MEETING COULD HAVE BEEN A NAP
```

The selected mode needs working vision and a gateway with EffectCraft and
FilmCraft available. Vision writes the punchline. EffectCraft renders two
static title cards, then FilmCraft builds this fixed timeline:

| Time | Content |
| --- | --- |
| 0–2 seconds | Dark blue opening card: **IN A WORLD...** |
| 2–7 seconds | Your photo, fitted without stretching, with **BASED ON A TRUE STORY. ALLEGEDLY.** at the bottom |
| 7–10 seconds | Matching closing card with the generated/requested punchline |

The result is 1280×720 at 24 fps, with straight cuts and no soundtrack or
subject animation. Optional direction controls the punchline; the opening and
setup wording remain fixed. The exported MP4 has an editable FilmCraft project
and media archive. An optional Canvas page saves the playback link.

The title renders use PNG so the completed trailer is the recipe's only MP4;
the existing Web player therefore selects the finished movie. EffectCraft's
animated title fade is not used in this recipe. The chain uses Stash exports
to combine independent gateway projects.

Every later render requires completed source files. If a title or the final
movie is still queued/running, the response names that stage and job ID, and
later stages stay unsubmitted. Inspect/collect that job. Collection does not
automatically resume a workflow: ask Jarvis to continue from the saved clips
and photo, using the timing table above. Running the command again creates a
new trailer. An error also retains the earlier successful files and any job
IDs returned by the failed stage.

Other practical combinations with the currently exposed tools:

| Idea | Tool chain | Current boundary |
| --- | --- | --- |
| Dramatic meme short | `/craft_meme_trailer`: `craft_motion` title PNGs → `craft_video` title + captioned photo + punchline | Static cards; no exposed pan/zoom or transition controls. |
| Bring a photo to life | `generate_video` with the photo's Stash reference as `image_url` → `craft_video` captions | AI motion comes from the configured video provider and can incur provider charges. |
| Reaction cut | `analyze_video` for broad context → `craft_video` selected source ranges and timed captions | Analysis samples frames; use known timestamps or review the cuts for precise boundaries. |
| Spoken-word subtitles | Supply timed text → `craft_video` caption overlays | Existing transcription returns text without subtitle timing; this is not automatic synchronized transcription or SRT import. |
| Remove pauses | Supply the ranges to keep → `craft_video` | No exposed automatic silence detector; do not guess silence from sampled frames. |
| GIF delivery | Additional conversion support would be needed | `convert_file` currently has no video-to-GIF route. Use MP4 for these recipes. |

For a multi-stage video recipe, continue only after each source job has
`state: succeeded` and a real `stash_ref`. An accepted/running job is not media
yet. Combine independent jobs through their Stash exports; their `craft://`
references may belong to different projects. Captions use times on the edited
timeline, while clip ranges use source times. Current video exports are at
most 120 seconds and fit within 1920×1080; portrait output must also fit those
bounds, for example 608×1080.

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
