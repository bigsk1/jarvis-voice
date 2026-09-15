# Private HTTPS for Jarvis with Tailscale

Use Tailscale Serve to access Jarvis from your phone, laptop, or desktop over
HTTPS without publishing the UIs to the internet. This is optional: existing
Jarvis installations continue to work with their normal HTTP addresses.

This guide uses a Linux Jarvis host. For Docker, run Tailscale on the Docker
host and follow the [Docker notes](#docker-notes). Install and configure Jarvis
first using the [installation guide](INSTALL_GUIDE.md) or
[Docker guide](docker/README.md).

**Every hostname here is a placeholder.** Replace `jarvis.example.ts.net` with
your server's full Tailscale DNS name. Keep your real addresses in local
configuration, not in edits to this public guide.

## What the setup does

Your browser connects to an HTTPS listener managed by Tailscale on the Jarvis
host. Serve forwards the request to the existing local HTTP UI. The application
does not need to manage certificates or change its listening port.

Serve follows your tailnet's access rules. It does not enable public Funnel or
require a router port-forward for the Jarvis website. See
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

The original HTTP listeners remain accessible wherever your existing binding
and firewall allow. In a standard native installation they bind to `0.0.0.0`;
LAN HTTP traffic remains plaintext. Making the entire deployment accessible
exclusively through Tailscale would require separate listener/firewall changes.

Jarvis's URL download guard also treats Tailscale destinations as internal:
it blocks the generic `100.64.0.0/10` IPv4 range and IPv6 unique-local addresses,
including IPv4-mapped forms. This applies to tool-supplied URLs and Stash URL
imports, including DNS names that resolve to those addresses. No personal IP
or hostname is built into the rule. Your browser/extension connection, local
`stash://` reads, and explicitly configured service endpoints use separate
paths. See [Stash URL security](STASH_SYSTEM.md#41-url-download-security-redirect-aware-ssrf-protection)
for the shared callers and DNS/proxy limitations.

| UI | Existing local backend | Suggested private HTTPS URL |
| --- | --- | --- |
| Web chat | `http://127.0.0.1:5001` | `https://jarvis.example.ts.net` |
| Canvas | `http://127.0.0.1:8890` | `https://jarvis.example.ts.net:8443` |
| Memory | `http://127.0.0.1:5002` | `https://jarvis.example.ts.net:8444` |
| Intelligence | `http://127.0.0.1:5003` | `https://jarvis.example.ts.net:8445` |
| Docs | `http://127.0.0.1:5004` | `https://jarvis.example.ts.net:8446` |

The HTTPS ports are a suggested layout. Separate ports preserve each app's root
paths, static files, API routes, and sockets. Do not substitute path prefixes
such as `/web` or `/canvas`; the UIs and extension do not support that deployment
layout. Web alone is enough to get started.

## 1. Prepare the host and devices

1. [Install Tailscale](https://tailscale.com/download) on the Jarvis host and each
   device you want to use. Connect them to your tailnet; Linux onboarding uses
   `sudo tailscale up` if the host is not already connected.
2. In the Tailscale admin console's DNS settings, enable MagicDNS and HTTPS
   Certificates. Certificate issuance publishes the full machine DNS name in
   certificate transparency logs; the website itself stays private. Follow
   [Tailscale's HTTPS setup](https://tailscale.com/docs/how-to/set-up-https-certificates).
   Serve manages its certificates; this workflow does not require manually
   running `tailscale cert` or copying certificate files into Jarvis.
3. Ensure your access rules allow the intended devices/users to reach the Jarvis
   host on TCP `443`, plus `8443`–`8446` if using the other UIs. Being in the same
   tailnet does not override restrictive rules. See
   [Tailscale access control](https://tailscale.com/docs/features/access-control).
4. Configure Jarvis's optional `WEBUI_PASSWORD` in the ignored
   `config/cloud.env` or `config/local.env` used by your deployment. Use consistent
   shared-auth settings across the UIs; see [WebUI authentication](auth/README.md).
   Tailscale network access does not replace the Jarvis login.

On the Jarvis host, inspect the current state before adding mappings:

```bash
tailscale version
tailscale status
tailscale serve status
systemctl is-active tailscaled
systemctl is-enabled tailscaled
```

Use current Serve syntax (Tailscale changed it in version 1.52). If another
service already occupies a suggested HTTPS port, choose a free one and adjust
the commands and navigation configuration. Do not reset existing mappings.

In the terminal where you will run the checks, set your real hostname:

```bash
JARVIS_HTTPS_HOST='jarvis.example.ts.net'  # Replace with your server's full DNS name.
```

Find that name on the server's Tailscale device details or in the URL printed by
Serve. Use the full `*.ts.net` name for certificate validation; a short name like
`jarvis` or a Tailscale IP is not interchangeable with that HTTPS hostname.

## 2. Start with Web

For a native installation, start Web if it is not already running:

```bash
cd ~/jarvis-voice
./bin/start web
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:5001/login
```

The launcher follows your selected `JARVIS_MODE`; use `./bin/start --local web`
for an explicitly local deployment. Docker users should start their existing
Compose deployment instead of launching a second native copy.

Once the local login page returns `200`, enable the Web proxy on the host:

```bash
sudo tailscale serve --bg 5001
tailscale serve status
curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' "https://${JARVIS_HTTPS_HOST}/login"
```

The final command should return `200` with normal certificate verification.
Do not use `curl -k` to hide certificate errors. Serve should report a
`(tailnet only)` HTTPS origin forwarding to `http://127.0.0.1:5001`.

Open that HTTPS URL on a connected Tailscale device. Sign directly into Web,
send a normal test message, and check that the connection stays connected.
HTTPS itself can work before a code upgrade/restart; the navigation helper in
the next sections requires a server version that includes it.

The commands use `sudo` because many Linux installations require it for Serve
configuration. If a password is requested, enter it in your terminal. No
passwordless-sudo or Tailscale operator change is needed.

## 3. Add the other UIs

For native installations, start any missing UI sessions:

```bash
cd ~/jarvis-voice
./bin/start --ui-only
```

Use `./bin/start --local --ui-only` when explicitly selecting local mode. The
launcher does not restart sessions that are already running. Confirm the
backends in the table are reachable, then add only the UIs you want:

```bash
sudo tailscale serve --bg --https=8443 8890
sudo tailscale serve --bg --https=8444 5002
sudo tailscale serve --bg --https=8445 5003
sudo tailscale serve --bg --https=8446 5004
tailscale serve status
```

Here `--https` selects the browser-facing port, and the final number is the
existing HTTP backend port. Repeating `serve --bg` with no `--https` selects
the same default port `443`, so specify a distinct HTTPS port for each UI.
For customized backend ports, change the final number accordingly.

Open each enabled HTTPS URL from a second Tailscale device. This also checks
the device's access rules; a successful check on the server alone does not.

## 4. Keep navigation on HTTPS

Without optional URL configuration, existing cross-UI buttons use their normal
HTTP ports. From the repository root, create the ignored configuration if it
does not already exist:

```bash
cp -n config/ui_urls.example.json config/ui_urls.json
```

Edit `config/ui_urls.json`, replacing the example hostname both as the `hosts`
key and in every URL. The [complete example](../config/ui_urls.example.json)
matches the five ports in this guide. Keep only the service entries you enabled;
missing entries keep their original link behavior.

Each value must be an HTTP(S) **origin**: scheme, hostname, and optional port.
Paths, query strings, fragments, and embedded credentials are rejected. The
helper preserves the existing destination path/query/fragment where applicable.

Overrides apply only when the browser visits the configured hostname. A visit
through a LAN IP or another unmatched hostname keeps the old links. Missing or
invalid configuration also falls back rather than stopping the UI.

Restart each UI once if you installed new server code. Finish active work before
stopping Web. For a tmux-managed UI, attach to its session, press Ctrl+C to stop
the server, and press Enter if the launcher displays its close prompt. Then
start that service again from a separate terminal:

```bash
tmux attach -t jarvis-web
```

```bash
cd ~/jarvis-voice
./bin/start web
```

The other session/service pairs are `jarvis-canvas`/`canvas`,
`jarvis-memory`/`memory`, `jarvis-intelligence`/`intelligence`, and
`jarvis-docs`/`docs`. Preserve the deployment's cloud/local mode.
Avoid `./bin/start --stop` for a UI-only restart: it also stops the API and
background services. Subsequent URL-file edits need only a page reload.

Hard-refresh the browser, then inspect the helper through HTTPS:

```bash
curl --fail --silent --show-error "https://${JARVIS_HTTPS_HOST}/ui-navigation.js"
curl --fail --silent --show-error "https://${JARVIS_HTTPS_HOST}:8443/ui-navigation.js"
```

The first line should identify your hostname and contain the configured HTTPS
origins under `urls`. Repeat for other enabled ports. A `404`, or HTML returned
instead of JavaScript, means the helper route is not loaded. An older UI's
fallback page can return `200`, so the status code alone is insufficient.
An empty `"urls":{}` means the request hostname did not match
valid configuration. The helper uses `Host`, not `X-Forwarded-Host`; the proxy
must preserve the browser's hostname. Tailscale Serve was verified to do so.

`config/ui_urls.json` and its `.bak` backup are excluded from Git and Docker
images. The generic `.example.json` is safe to track. You can confirm with
`git check-ignore -v config/ui_urls.json`.

## Docker notes

Use the [Docker guide](docker/README.md) to start the stack. Memory, Intelligence,
and Docs use the `extras` profile. Run Serve on the Docker host, targeting the
**published host ports**; container service names are not host proxy targets.
If root `.env` changes a `JARVIS_*_PORT`, use that published port as the Serve
backend target. Keep the container's own internal port unchanged.

The shipped Compose file already mounts `./config:/app/config:ro` into every UI.
Creating/editing host `config/ui_urls.json` therefore requires no extra mount or
container recreation. A custom deployment must make that file available at
`/app/config/ui_urls.json`.

Installing newly added navigation code into existing images does require a
rebuild/recreation. For an existing standard deployment using all five UIs,
after finishing active work:

```bash
docker compose --profile extras up -d --build --no-deps jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs
```

Target only the UIs you use. Preserve the same `-f`, `--env-file`, and `-p` options
as your existing deployment, including both Compose files for an MCP deployment.
Do not run a second native stack against the same data. No `down`, volume removal,
certificate mount, or API proxy is required.

## Browser, extension, and API behavior

- **Web sign-in:** signing into another UI first may still cause Web to request
  its own login behind HTTPS. Direct Web login supplies the explicit socket
  token; this avoids relying solely on a cookie-origin check against the HTTP
  upstream. Do not disable authentication to resolve a reconnect loop.
- **Firefox extension:** use `https://jarvis.example.ts.net` as its server URL
  and sign in for that origin. It connects to the Web server, not FastAPI, and
  sends an explicit token. HTTP insecure-mode opt-in is unnecessary for this URL.
  See the [extension guide](../jarvis-firefox-extension/README.md).
- **Microphone:** HTTPS satisfies the browser secure-context requirement, but
  microphone permission and a working STT provider are still needed. Test on
  each device. Safari may record MP4 while the current upload path labels the
  recording WebM; HTTPS alone does not resolve that compatibility issue. See
  [Jarvis speech-to-text](SPEECH_TO_TEXT.md) and
  [browser microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).
- **Canvas links:** navigation and preview overrides do not rewrite old saved
  URLs. `CANVAS_PUBLIC_URL` in your ignored mode configuration separately controls
  new server-generated Canvas links. Keep `CANVAS_INTERNAL_URL` pointed at the
  internal service; never replace internal container URLs just to change a
  browser address.
- **FastAPI:** leave its existing port `8880` outside this setup. Native defaults
  bind all interfaces; the standard Docker host publication binds loopback.
  FastAPI has separate optional API-key authentication and a loopback exemption.
  Review client-IP/proxy handling before adding its own HTTPS proxy. A Web login
  token is not the FastAPI key. See [API security](api/SECURITY_OPTIONS.md).

## Status and troubleshooting

### Connection indicator in Web

Open **Settings → Profile** to see the optional Tailscale box below System Info.
It checks when Profile opens or you press **Refresh**; server results are cached
for up to 15 seconds. It does not install, enable, disable, or reconfigure Tailscale.

| Indicator | Meaning |
| --- | --- |
| Connected | This page uses HTTPS on a verified private Serve listener, the server reports Tailscale online, and Web chat is connected. |
| Reconnecting | The private HTTPS endpoint was verified, but the chat connection is reconnecting. |
| Not in use | Tailscale is running, but this page is using a different address or HTTP connection. |
| Public HTTPS | The matching HTTPS listener has public Funnel enabled. |
| Not enabled / Disconnected | The native server has no Tailscale CLI, or Tailscale is not connected. |
| Unverified / Unavailable | The server cannot establish the status; HTTPS alone does not prove private Serve access. |

Docker commonly runs Tailscale on the host while the CLI/daemon is unavailable
inside the Web container. The indicator reports that limitation rather than
claiming Tailscale is disabled. A configured navigation URL or `*.ts.net` suffix
alone is not enough to show a verified private connection.

The existing **Auth Status** tile describes Jarvis login protection. The Tailscale
box describes this connection; neither means the original LAN listeners are closed.

### Command-line checks

```bash
tailscale status
tailscale serve status
tailscale serve status --json
tailscale funnel status
systemctl is-active tailscaled
ss -ltnp
```

**Why does `funnel status` show proxies?** Serve and Funnel share serving
configuration, and the status command lists running servers. `(tailnet only)`
means private access; `proxy` identifies the local destination. Running a status
command does not enable Funnel. In JSON, an enabled `AllowFunnel` entry means
public Funnel access for that address; a configuration with no enabled entries
has no public Funnel listener. See [Funnel status documentation](https://tailscale.com/docs/reference/tailscale-cli/funnel#get-the-status).

| Symptom | Check or action |
| --- | --- |
| `serve config denied` or sudo password required | Run the Serve command with `sudo` in the host terminal. |
| HTTPS setup needs admin authorization | Follow the CLI's setup link and enable HTTPS Certificates/MagicDNS with your tailnet administrator. |
| Certificate error | Use the full hostname printed by Serve; check device time and HTTPS setup. Do not bypass certificate validation. |
| Local HTTP login check fails | Start the UI or inspect its tmux/container logs; confirm the backend port. |
| HTTPS returns a proxy/backend error | Compare Serve's target with the working loopback URL or Docker published port. |
| Works on the host but not another device | Check the device's Tailscale connection, DNS, and access rules for the HTTPS port. |
| Web works on 443 but another HTTPS port fails | Check that listener with `serve status`, its backend, and access rules for 8443–8446. |
| Buttons open HTTP or the helper shows `"urls":{}` | Check the hostname key, valid origins, proxy Host, and Docker config mount; hard-refresh. |
| `/ui-navigation.js` returns 404 or HTML instead of JavaScript | Restart the updated native UI or rebuild/recreate its Docker image; a fallback HTML page can return 200. |
| Web repeatedly requests login or reconnects | Sign directly into Web at its HTTPS URL, hard-refresh updated scripts, and verify the WebSocket connection. |
| Mic works on desktop but fails on iPhone | Check Safari permission and STT response; investigate the recording MIME format separately. |
| An old Canvas link opens HTTP | Stored links keep their original URL; use HTTPS navigation or update the optional public Canvas URL for new links. |

## Reboots, stopping, and rollback

Serve mappings started with `--bg` persist and resume after Tailscale restarts.
Check `systemctl is-enabled tailscaled` on Linux. Jarvis processes have their
own lifecycle: tmux sessions do not survive a host reboot, so start Jarvis as
usual (or `./bin/start --ui-only`). Docker follows its configured restart policy.
See [Serve persistence](https://tailscale.com/docs/reference/tailscale-cli/serve#effects-of-rebooting-and-restarting).

Disable individual HTTPS listeners using their browser-facing ports:

```bash
sudo tailscale serve --https=443 off
sudo tailscale serve --https=8443 off
sudo tailscale serve --https=8444 off
sudo tailscale serve --https=8445 off
sudo tailscale serve --https=8446 off
tailscale serve status
```

Run only the lines for listeners you intend to remove. Restart a removed mapping
with its original `serve --bg` command. This leaves the UIs, their HTTP ports,
and Tailscale itself running. Avoid `tailscale serve reset` or
`tailscale funnel reset` unless you intend to clear the shared serving configuration, including
unrelated mappings.

To restore default navigation too, move the ignored configuration aside and
reload the browser (preserve an existing backup before doing this):

```bash
cd ~/jarvis-voice
mv -i config/ui_urls.json config/ui_urls.json.bak
```

Restore it by moving the backup back and reloading. If you separately changed
`CANVAS_PUBLIC_URL`, restore that value and restart the affected Jarvis processes.
Stopping Serve does not undo that optional setting automatically.
