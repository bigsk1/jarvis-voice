# Jarvis Head (matrix kiosk)

**Status:** Phases 0–5 accepted. Optional host display, not part of install or Docker.

**Startup policy:** Manual only for v1, including Phase 5. Nothing starts the head from an existing tmux session, `start-all`, the Jarvis dashboard, an installer, an enabled systemd unit, or the wake process. Hooks only send optional datagrams; they never launch or supervise the display. `bin/kiosk.sh start` creates a bounded **transient** systemd service only when explicitly requested; it is never installed or enabled at boot.

A fullscreen terminal on a monitor plugged into the Jarvis host. Idle is matrix rain. Wake word coalesces a face out of the rain. Blink and a little drift while listening. Mouth tracks TTS while `aplay` runs.

Look targets:

- `docs/personal/talking-head/matrix-idea.png` — the real matrix-crypto rain (Windows screenshot). Green columns, black gutters. That is the engine.
- `docs/personal/talking-head/matrix-face-idea.jpg` — rain that *is* a face. Drop the CRT bezel. The panel *is* the object.

This is not a 3D hologram, not SadTalker, not a browser kiosk, and not an LLM tool.

Rain code comes from [bigsk1/matrix-crypto](https://github.com/bigsk1/matrix-crypto) (same author). Adapt the column loop. Do not submodule it. Do not keep CoinGecko.

## Why this shape

TTS is already a wav on disk, then `aplay` on this host. The display is an independent process on a second TTY. Wake stays in its tmux session. The head never owns or launches wake, TTS, `aplay`, the orchestrator, or the API. The remaining latency is TTS generation, same as today.

## Non-goals (v1)

- Photoreal skin, 3D tilt, arc-reactor bust, hologram hardware
- Chromium kiosk, WebSocket to a phone, GPU talking-head generators
- Blocking `aplay` while an envelope or visemes compute
- A skill the model can call
- Web-UI-only TTS (`POST /api/tts` in the browser)
- Shipping this in Docker or `install.sh`
- Positioning a window onto a panel from the app (`DISPLAY=:0` is an X server, not a monitor)

## Layout

Application directory, same idea as `jarvis-canvas/`: `bin/jarvis-head` puts that directory on `sys.path` and imports `app`, `rain`, `mask`. It is **not** an importable package named `jarvis-head` (hyphens). Do not add a decorative `__init__.py` that pretends otherwise. The publisher lives in `lib/` so wake and TTS never import curses.

```
bin/jarvis-head              # display, demo, emit
bin/kiosk.sh                 # manual Linux-VT start / stop / status wrapper
lib/head_events.py           # fire-and-forget Unix datagram send
jarvis-head/                 # application directory (not a Python package)
  app.py                     # curses loop + nonblocking event polling
  head_protocol.py           # bounded JSON validation
  head_socket.py             # singleton lock + secure datagram lifecycle
  head_state.py              # base state + speech overlay
  rain.py                    # MatrixColumn, adapted from matrix-crypto
  mask.py                    # authored masks → cell intensities (aspect-corrected)
  visemes.py                 # wav → mouth timeline (four-aperture envelope first)
  assets/
    face.png                 # authored semantic mask: 0 outside the head
    face-blink.png           # authored eyes-closed control
    mouth-rest.png           # authored four-aperture controls
    mouth-ae.png
    mouth-o.png
    mouth-closed.png
```

Core display and event commands:

```bash
./bin/jarvis-head                    # kiosk preset (solid field)
./bin/jarvis-head --preset reference # original guttered density
./bin/jarvis-head --fps 45           # optional 1–120 FPS cap (default 30)
./bin/jarvis-head --seed 42           # fixed visual sequence for comparisons
./bin/jarvis-head --demo-face         # force the authored face, no wake/events
./bin/jarvis-head --demo-face --cell-aspect 0.4
./bin/jarvis-head --demo-wav PATH     # looping visual envelope; never plays audio
./bin/jarvis-head emit listen
./bin/jarvis-head emit think
./bin/jarvis-head emit speak --wav PATH --playback-id ID --t0 EPOCH
./bin/jarvis-head emit speak_end --playback-id ID --ok true|false
./bin/jarvis-head emit sleep
```

The emit commands support isolated testing and are now used by the default-off Phase 4 TTS/wake hooks. They never launch the display.

Python callers (wake scripts) import `lib/head_events.py`. Bash callers use `emit`. If nothing is bound, emit is a silent no-op. TTS never depends on the display being up. The `emit` CLI path must lazy-import only configuration and `head_events`; it must not import curses, Pillow, masks, or the display application.

## Event protocol

Unix datagram socket.

Default path: `/tmp/jarvis-head-$UID/head.sock` (compute the uid with `os.getuid()`, not an assumed exported `$UID`). Its per-user directory is private (`0700`) and remains available if the launching SSH/logind session ends; this keeps the independently running display, wake, and TTS processes on one endpoint. Override with an absolute `JARVIS_HEAD_SOCKET`; relative paths are rejected so processes with different working directories cannot split across sockets.

For the default, create the leaf runtime directory mode `0700`; socket mode `0600`. For a custom path, do not chmod an arbitrary existing parent directory: require a safe writable parent or create only the missing leaf directory.

Bind rules:

- Before touching the socket, acquire and hold a nonblocking advisory lock in the same private runtime directory for the display's lifetime. If the lock is held, another display is active: refuse to start. A second display must never unlink and steal the active display's socket.
- After acquiring the lock, if the path exists, require that it is a socket owned by the current uid before unlinking it as stale. Refuse to unlink a regular file, symlink, device, or another user's socket.
- Unlink the socket and release the lock on SIGINT / SIGTERM / normal exit. SIGKILL may leave the socket inode, but releases the kernel lock; the next start removes the owned stale socket after acquiring that lock.
- Bound datagram size (drop anything over a few KiB). Bound WAV size before the display reads it.
- Validate the wav path: regular file, readable, RIFF/WAVE header. Reject missing, empty, directories, and device nodes. On reject, ignore that `speak` (do not crash the rain).

JSON one datagram per event:

| type | when | payload |
|------|------|---------|
| `listen` | wake word accepted, before greeting TTS | `{}` |
| `think` | question capture / orchestrator running (optional) | `{}` |
| `speak` | **inside the playback lock**, immediately before each `aplay` attempt | `{playback_id, wav, t0}` |
| `speak_end` | that attempt finished | `{playback_id, ok}` |
| `sleep` | wake loop re-armed | `{}` |

`playback_id` is unique per `aplay` attempt (not per wav). A retry is a new id. The display ignores `speak_end` whose id is not the active overlay. `t0` is unix epoch with fraction (`date +%s.%N` / `time.time()`). Align the mouth to `t0`, not packet arrival.

`say.sh` and `say-local.sh` intentionally pad ~200ms of silence with sox before play so the beginning of wake-triggered speech is not clipped. Status TTS uses its configured `STATUS_SILENCE_PAD_MS` (250ms by default). The envelope includes this audio; these pads are separate from the smaller enabled-emitter startup overhead immediately before `aplay`.

Status scripts may delete a temp wav after play. On `speak`, load the wav (or its envelope) into memory immediately. Cached status files under `~/.cache/jarvis/status-tts/` are not deleted; still copy or parse before `aplay` returns.

WAV duration is the display fail-safe: if `speak_end` never arrives, end the overlay when `t0 + duration + slack` elapses.

## Hook points

**Implemented in Phase 4** (one helper, not a UniFi-specific hook): every script that plays through `bin/tts-common.sh` → `jarvis_tts_play_audio` → `aplay`. That is `say.sh`, `say-local.sh`, `say-status.sh`, `say-status-local.sh`, and everything that calls those: wake greetings, question-orchestrator answers, UniFi alerts via `alert_manager`, follow-up daemon, reminder scheduler, self-healing, in-task status phrases.

**Out of scope until explicitly hooked:** leftover scripts that call `aplay` themselves (`bin/question.sh`, `bin/question-local.sh`, `bin/question-mic.sh`). Browser `POST /api/tts`. Docker proactive speech.

Do not hook the orchestrator, Web Socket.IO, or the LLM.

### Speak emit lives inside the lock

`jarvis_tts_play_audio` can block up to `TTS_PLAYBACK_LOCK_TIMEOUT` (default 30s) on `flock`. Emitting at function entry would start the mouth while another utterance still holds the speaker.

Phase 4 emits in `jarvis_tts_play_audio_once`, **after** the lock is held, immediately before each `aplay`. It generates a unique `playback_id` for that attempt. After `aplay` returns, it emits `speak_end` with that id and success/failure. The enabled playback attempt has a scoped `EXIT` cleanup, so terminating a status-TTS process group during `aplay` emits a failed `speak_end` instead of relying on the WAV-duration fail-safe. It never waits on the display.

If flock is missing, the retry loop still emits per attempt the same way.

Keep emit behind `JARVIS_HEAD_ENABLED` (default off). Python callers return immediately from `head_events.emit` when unset or false. `tts-common.sh` must perform the same cheap truthy check **before launching the Python CLI**, so disabled installations pay no per-utterance Python startup cost.

The publisher uses a nonblocking Unix datagram socket and a bounded payload. Missing socket, stale receiver, full receive queue, malformed override path, and all other send failures are silent by default. They must not delay playback, change the `aplay` exit status, or affect retry behavior. Optional diagnostics require `JARVIS_HEAD_DEBUG=true`.

Wake scripts still emit `listen` / `sleep`. While the Q&A child process is alive, they renew `listen` every 30 seconds so a long recording, transcription, or tool-heavy orchestrator run cannot age out the default 120-second face lease. The keepalive stops before re-arm or exit cleanup. Alerts do not need it: a `speak` while asleep is enough.

## Failure boundary: the head cannot take Jarvis down

The display is an optional peer process, not a child service that Jarvis supervises and not a library loaded by wake, TTS, the API, or the orchestrator. Events travel one way. There is no acknowledgment or health dependency in the Jarvis path.

If the head crashes, is killed, loses its TTY, rejects a wav, or is not running at all, the only loss is the visual. Wake capture, TTS generation, the playback lock, `aplay`, alerts, and re-arm continue exactly as they do with `JARVIS_HEAD_ENABLED=false`. Every emitter call is fail-open (`|| true` or equivalent) while preserving the real playback status.

Process separation does not prevent resource contention, so the display also has hard bounds:

- Frame rate is capped; animation uses monotonic delta time rather than running as fast as possible.
- Terminal-sized rain/mask arrays and WAV reads are bounded. No unbounded event queue, retry queue, log, or decoded-audio cache.
- Render or decode exceptions terminate or reset only the display. Do not catch an exception and spin a hot restart loop inside `app.py`.
- Keep systemd out of v1. If supervision is added later, use delayed/rate-limited restart and optional CPU/memory controls; never rapid `Restart=always`.

## State: base + speech overlay

Speech is not a third peer of sleep/listen. Status TTS arrives with no preceding `listen`.

```
base_state     = SLEEP | LISTEN | THINK
speech_overlay = inactive | playback(playback_id, t0, duration)
```

| Situation | What the screen does |
|-----------|----------------------|
| `SLEEP` + overlay inactive | Rain only |
| `SLEEP` + `speak` | Face materializes, mouth follows that `playback_id`, dissolve back to rain when overlay ends |
| `LISTEN` / `THINK` + overlay inactive | Face, blink, 1–2 cell drift |
| `LISTEN` / `THINK` + `speak` | Same face, mouth follows `playback_id`, return to listen/think (do not dissolve) |
| `sleep` event | Set base state to `SLEEP`; an active speech overlay finishes normally, then dissolve to rain |
| Retry `speak` with a new id | Switch overlay to the new id; ignore later `speak_end` for the old id |
| Stale `speak` (old `t0`, or overlay already on a newer id) | Ignore |
| No events while `LISTEN`/`THINK` for `JARVIS_HEAD_IDLE_TIMEOUT` | Force `SLEEP` so a crashed wake process cannot leave the face up |

`LISTEN` stays up across greeting TTS + Q&A + answer so the face does not dissolve between “yes?” and the reply. Overlay is the mouth. UniFi / reminders never set `LISTEN`.

Idle motion:

- Glyph texture: mutate a scattered subset on a slower cadence than the rain. The semantic intensities and facial coordinates stay fixed, so the face remains readable without looking frozen.
- Keep glyph state independent from expression and pose. A blink or drift must not rerandomize the full face; glyph mutation continues naturally underneath both.
- Blink: swap only the `face-blink.png` eye ROI values for 2–3 frames, random 2–6s. Preserve the current glyph field.
- Drift: do not rotate glyphs or regenerate the mask. Apply a 0–2-cell draw offset to the composed face, including its current glyph field and active eye/mouth values.

## Rain density (the screenshot)

`matrix-idea.png` is the current look: one stream per column, black alleys between them. That is `BACKGROUND_PATTERN` (`[1, 2, 3, 1]` means draw one column, skip 1–3 cells). Columns are also short (`BACKGROUND_COLUMN_LENGTH_RANGE` about 0.3–0.6 of height), so the field never fills.

Matrix Crypto took repeated tuning to make its column lifecycle stable. Preserve that work deliberately:

- Start from the offline `MatrixColumn` initialization/update/reset mechanics and record the exact upstream commit in `rain.py`.
- Separate the proven column model from Jarvis's curses renderer, mask, and event loop. Do not rewrite column movement and face composition at the same time.
- Give `RainField` an injectable `random.Random` instance. Demos and tests can use a fixed seed; normal display startup uses a fresh seed.
- First reproduce the known guttered Matrix Crypto look as a `reference` preset. Only after that matches should a separate `kiosk` preset change gaps, lengths, and speed for the solid field. The stable mechanics stay the same.

Kiosk idle should be a solid field. Same class, different numbers:

- `BACKGROUND_PATTERN = [0]` (or skip the gap loop): a column on every x
- Longer streams, closer to full height, so vertical holes close
- Slightly faster `BACKGROUND_FALL_SPEED_RANGE` if it still feels sparse
- Opaque terminal. The Windows shot shows chat UI through the glass. The head monitor is black.

Crypto tickers in matrix-crypto were a second *pass* in the same loop. The face replaces that pass. It does not replace the rain. No compositor overlay.

## Rain + face

A face-shaped hole in the rain reads as a black blob. Keep raining everywhere. The mask is a per-cell multiplier:

| Mask region | What the cell does |
|-------------|--------------------|
| Outside the head (value 0) | Normal rain |
| Skin / skull | Denser, brighter, glyphs change less often (rain “locks”) |
| Eyes / nose highlights | Brightest green band; white is reserved for rain leads |
| Mouth | The only real negative space: which aperture PNG is active |

One `addstr` loop. After drawing a rain cell, if the mask says so, change intensity / hold the char / skip drawing (mouth hole).

Do **not** derive `face.png` by cropping the idea JPEG to grayscale. Author semantic masks: zero outside the head, calibrated eye highlights, separate mouth apertures. The JPEG is a look reference, not the asset pipeline.

Terminal cells are taller than they are wide. Mapping a square mask 1:1 onto (cols, rows) stretches the face. `mask.py` applies a configurable cell-aspect correction (`JARVIS_HEAD_CELL_ASPECT`, default `0.4` = cell width/height in pixels, accepted on the dedicated panel) when fitting the mask into the terminal grid. Recompute on `KEY_RESIZE`.

Curses on a real monitor is ~200×50 to 240×70 cells. Pores will not survive. Eyes as the brightest cells will. Use 256-color if `TERM` allows; fall back to green + `A_BOLD` / `A_DIM`.

`BACKGROUND_CHARS` can add half-width katakana later if the kiosk font has them. ASCII is enough for the first rain on the panel.

The 10ms sleep in matrix-crypto is a visual reference, not a kiosk contract. A 200×70 terminal redrawn at 100 FPS can waste a CPU core while the panel displays 60 FPS or less. Use `time.monotonic()` for delta time and target roughly 30–60 FPS. Phase 0 chooses the lowest rate that still looks fluid on the real panel and verifies that the display does not create sustained CPU pressure on Jarvis.

Pillow is already in `pyproject.toml` and `requirements.txt`.

## Mouth

The implemented first mouth uses 50ms RMS and spectral windows quantized to four apertures: rest, closed, AE/open, and O/round. Analysis happens once before curses starts. It streams through the WAV and retains only the small aperture timeline, not decoded audio.

`--demo-wav` accepts bounded uncompressed PCM WAV files (8/16/24/32-bit, 8–96kHz, up to 8 channels), with limits of 64 MiB and 300 seconds. It loops the visual timeline with a short neutral pause and never calls `aplay` or another player. Silence uses rest, low relative energy uses closed, strong low-centroid voiced frames use O/round, and the remaining strong frames use AE/open. Single-frame classification spikes are smoothed.

Rhubarb (or any viseme map) has to earn its way in with a side-by-side demo against that envelope. Do not add it in the first playback hook. If it ships later, compute on the display from the wav in `speak`, never delay `aplay`.

Never drive the jaw from live microphone volume.

## Dedicated monitor (Linux virtual terminal)

Wake tmux and the head do not share a terminal.

The supported Phase 5 target is a systemd-based Linux host with kernel virtual consoles and the `kbd`/`util-linux` commands `openvt`, `chvt`, `fgconsole`, and `runuser`. This is normal on headless Ubuntu and broadly reproducible across comparable Linux servers. Systems without `/dev/ttyN`, systemd, or these commands can still run `bin/jarvis-head` directly in an attached terminal, but cannot use this wrapper.

`bin/kiosk.sh start` captures the currently active VT, refuses `tty1`, refuses a target with an active getty, and launches the head on `JARVIS_HEAD_KIOSK_VT` (`tty8` by default). It uses `openvt -s -w` inside a manually created transient systemd service. The service survives loss of the launching SSH connection, has one control group for reliable stop, and is constrained to 50% of one CPU and 256 MiB by default. The wrapper itself runs with console privileges, but uses `runuser` so the display runs as the invoking non-root user and therefore shares the same UID-owned event socket as wake and TTS. Running `start` again while the unit is active switches the physical panel back to its configured kiosk VT without creating a second unit.

Normal exits (`q`, Escape, or Ctrl+C), failures, and `bin/kiosk.sh stop` return the monitor to the captured VT. If curses stops responding, Linux handles `Ctrl+Alt+F1` below the application and returns to the primary login console. Keep `getty@tty1.service` enabled; an optional second getty is additional recovery, not a kiosk dependency.

`DISPLAY=:0` names an X server, not a monitor. This headless-host wrapper does not install a GUI terminal, window-manager rule, compositor, persistent service, or autostart. Do not add it to existing Jarvis tmux sessions, `bin/start`, or the dashboard. A future persistent service or explicit `bin/start --with-head` remains an opt-in follow-up after live acceptance.

## Config keys

The same commented examples live in `config/cloud.env.example` and `config/local.env.example`:

```bash
# Optional matrix face kiosk on a host monitor. Emit is a no-op unless enabled
# and bin/jarvis-head is bound to the socket.
# JARVIS_HEAD_ENABLED=false
# JARVIS_HEAD_SOCKET=   # optional absolute path; otherwise use the private default
# JARVIS_HEAD_CELL_ASPECT=0.4
# JARVIS_HEAD_IDLE_TIMEOUT=120
# JARVIS_HEAD_KIOSK_VT=8
# JARVIS_HEAD_RETURN_VT=   # default: active VT when kiosk.sh starts
# JARVIS_HEAD_KIOSK_USER=  # default: invoking non-root user
# JARVIS_HEAD_KIOSK_CPU_QUOTA=50%
# JARVIS_HEAD_KIOSK_MEMORY_MAX=256M
```

Do not invent a new mode. Cloud vs local already chooses `say.sh` vs `say-local.sh`. The head does not care which LLM ran.

## Phases and done checks

Stop after any phase if the look is wrong; later phases will not save a bad mask. Envelope first; Rhubarb only after a side-by-side on the panel.

| Phase | Ship | Done when |
|-------|------|-----------|
| 0 | Adapted rain engine + `reference` / `kiosk` presets + `bin/jarvis-head` | Fixed-seed `reference` reproduces Matrix Crypto's known guttered behavior; `kiosk` is fullscreen with **no gutters**, opaque black, and fluid at a measured 30–60 FPS without sustained CPU pressure; Ctrl+C restores cursor and terminal cleanly |
| 1 | Authored semantic face mask + aspect correction + `--demo-face` | On the **actual panel**, it reads as a face from across the room. Eyes brightest. Not a bright rectangle. Not a stretched oval |
| 2 | Blink, 1–2 cell drift, `--demo-wav` four-aperture envelope | Idle looks alive. Mouth tracks a canned wav without `aplay` or wake |
| 3 | Socket + state machine **tests** (no live TTS required) | Speech-from-sleep, retry ids, stale events, missing/malformed wavs, malformed datagrams, idle timeout, singleton lock, stale-socket recovery, clean socket unlink |
| 4 | Live hooks: emit inside `jarvis_tts_play_audio_once`, both wake scripts | UniFi / `say-status` / wake greeting move the mouth. TTS still plays with a missing, crashed, or failing head. Shell tests prove emit happens **after** flock and cannot change playback status |
| 5 | Manual `bin/kiosk.sh` + transient systemd unit + dedicated Linux VT | One explicit command switches the physical monitor to an unused VT; every stop/exit path restores the prior console. No tmux, boot, login, persistent-service, or `bin/start` integration |

Phase 0 automated verification (2026-09-01): fixed-seed model tests pass; ruff passes; kiosk `q` exit and reference Ctrl+C exit both returned 0 in a 200×50 pseudo-TTY. At 30 FPS that harness measured approximately 13% CPU and 16 MiB RSS. The dedicated host monitor was visually accepted; Termius is known to wash out the black background and is not the acceptance target.

Phase 1 automated verification (2026-09-01): the authored grayscale mask is fitted from its active silhouette rather than its square image canvas, terminal cell width/height is corrected with the panel-accepted default of `0.4`, and resize rebuilds the fitted mask. Unit tests cover aspect fitting, zero-valued exterior, non-rectangular coverage, eye-highlight range, an internal dark aperture, and deterministic scattered glyph mutation. In a paired 200×50 pseudo-TTY sample at 30 FPS, rain-only used about 21% of one CPU core and the face used about 22%, with roughly 22 MiB RSS; `q`, Ctrl+C, and live resize all exited cleanly and restored the cursor. The dedicated-panel face and glyph motion were accepted before Phase 2.

Phase 2 automated verification (2026-09-01): 21 focused Phase 0–2 tests pass and cover expression-region isolation, glyph preservation across expression swaps, fixed-seed blink/drift, two-cell motion bounds, demo looping, four-aperture quantization, invalid WAVs, and file/duration limits. In 200×50 pseudo-TTY smoke tests, blink/drift and WAV-mouth demos used about 22% of one CPU core; lazy audio imports kept face-only RSS near 26 MiB, while the NumPy-backed WAV demo peaked near 40 MiB. `q`, Ctrl+C, and live resize exited cleanly and restored the cursor. Blink, drift, dynamic face glyphs, and WAV mouth motion were accepted on the dedicated panel before Phase 3.

Phase 3 automated verification (2026-09-01): 44 focused Phase 0–3 tests pass, including disabled and unavailable publishers, nonblocking queue failure, debug-only diagnostics, a real datagram round-trip, bounded malformed input, singleton refusal, owned stale-socket recovery, file/symlink protection, private modes, speech from sleep/listen, sleep during speech, retry and stale ids, invalid WAVs, idle timeout, and duration fallback. A full pseudo-TTY smoke sequence sent `listen`, `think`, `speak` with a real cached status WAV, matching `speak_end`, and `sleep`; every emit and the display returned 0 without playing audio, and the socket was removed. A separate SIGTERM run also returned 0 and removed its socket. No TTS, wake, playback-lock, or `aplay` path is changed in this phase.

Phase 4 automated verification (2026-09-01): 64 focused Phase 0–4 tests pass. The wake and playback test files also pass in both collection orders, proving their standard-library mocks are restored between tests. Shell tests prove disabled mode never invokes the emitter; each retry emits a unique id after the playback lock, followed by a matching success/failure end; terminating a blocked playback process group emits its matching failed end; a queued waiter emits nothing until it owns the lock; and an emitter failure cannot change retry count or playback success. Behavioral cloud/local wake tests cover normal re-arm, voice exit, question-process failure, long-Q&A keepalive, Ctrl+C, and startup failure, with every path returning the head to `SLEEP`. A pseudo-TTY display accepted the real emitter around a real cached WAV while a fake `aplay` returned success; no audio played, both processes returned 0, and the socket was cleaned up. The face palette test keeps all mask intensities in the selected color while reserving white for rain leads. No startup, tmux, dashboard, installer, or service file is changed.

Phase 5 verification and operator acceptance (2026-09-01): six fake command/config tests plus an absolute-socket regression bring the focused Phase 0–5 suite to 71 tests. They cover selected-mode head-only config hydration with explicit-override preservation, repo/legacy venv selection, a logout-stable private socket, relative-socket rejection, transient-unit construction, CPU/memory limits, head argument forwarding, non-root display ownership, active-start VT switching, `start`/`stop`/`status`, primary-console protection, active-getty refusal, and return-VT cleanup after display exit. On the real headless host, the transient unit switched the attached monitor to `tty8`, stopped cleanly, and allowed a direct SSH-terminal launch afterward; attempting that launch while the kiosk held the singleton produced the expected warning. Red and green palettes were accepted. On the small panel, reducing the explicit cap from 30 to 20 FPS looked the same while observed CPU fell from approximately 42% to 30.5%. The default remains 30 FPS; 20 FPS is an available operator tuning choice. No persistent unit, alias, tmux session, dashboard action, boot hook, or `bin/start` change is installed.

Optional later: Rhubarb vs envelope side-by-side. Hook `question.sh` / `question-local.sh` / `question-mic.sh` only if those leftover `aplay` paths still matter.

## Manual command reference

Run these from the repository root. The head always starts manually; emit, TTS, and wake commands never launch it.

### Start on the dedicated physical monitor

Stop any copy of `bin/jarvis-head` already running directly on the local console, then run from SSH:

```bash
./bin/kiosk.sh start
./bin/kiosk.sh status
./bin/kiosk.sh stop
```

`start` may request sudo authentication for VT control. It returns after creating the transient unit; losing SSH does not stop the kiosk. On the physical keyboard, use `q`, Escape, or Ctrl+C for a clean exit, or `Ctrl+Alt+F1` to switch directly to the primary login console. Starting again while active switches the panel back to the kiosk VT without creating another unit.

Pass display arguments after `--`:

```bash
./bin/kiosk.sh start -- --fps 45 --color green --cell-aspect 0.4
```

Useful kiosk recipes:

```bash
# Lower-redraw mode accepted on the small VT panel.
./bin/kiosk.sh start -- --fps 20

# Lower-redraw red variant with the accepted panel geometry.
./bin/kiosk.sh start -- --fps 20 --color red --cell-aspect 0.4

# Original guttered Matrix density instead of the solid kiosk field.
./bin/kiosk.sh start -- --preset reference --fps 20

# Repeatable visual sequence for comparisons and screenshots.
./bin/kiosk.sh start -- --seed 42 --fps 20
```

An active kiosk keeps its original arguments; another `start` only switches the panel back to its VT. To apply different flags, stop it first and start it again:

```bash
./bin/kiosk.sh stop
./bin/kiosk.sh start -- --fps 20 --color red
```

Choose another unused VT or an explicit return console when needed:

```bash
JARVIS_HEAD_KIOSK_VT=9 JARVIS_HEAD_RETURN_VT=1 ./bin/kiosk.sh start
JARVIS_MODE=local ./bin/kiosk.sh start  # read optional head settings from local.env
```

The wrapper reads optional settings from the selected `cloud.env` or `local.env`; explicit command-environment values win. It refuses `tty1` and a target with an active getty. It does not enable itself at boot.

### Start and tune the display

```bash
./bin/jarvis-head                              # normal rain + event receiver
./bin/jarvis-head --cell-aspect 0.4            # accepted dedicated-panel geometry
./bin/jarvis-head --preset reference           # original guttered Matrix look
./bin/jarvis-head --fps 45 --color green       # render cap and color
./bin/jarvis-head --seed 42                    # repeatable visual sequence
./bin/jarvis-head --help                       # all display options
```

Color choices are `green`, `cyan`, `blue`, `red`, `yellow`, `magenta`, and `white`. Press `q`, Escape, or Ctrl+C to exit.

Color examples for a direct terminal launch:

```bash
./bin/jarvis-head --color green
./bin/jarvis-head --color cyan
./bin/jarvis-head --color blue
./bin/jarvis-head --color red
./bin/jarvis-head --color yellow
./bin/jarvis-head --color magenta
./bin/jarvis-head --color white
```

### Visual-only face and WAV demos

```bash
./bin/jarvis-head --demo-face --cell-aspect 0.4
./bin/jarvis-head --demo-wav /absolute/path/to/speech.wav
```

`--demo-wav` loops the mouth animation and never plays the WAV.

### Send state events manually

Leave the normal display running, then use another terminal. Enabling the publisher in the sender terminal does not start the display.

```bash
export JARVIS_HEAD_ENABLED=true

./bin/jarvis-head emit listen                  # show listening face
./bin/jarvis-head emit think                   # show thinking face
./bin/jarvis-head emit sleep                   # return to rain
./bin/jarvis-head emit --help
```

Test the speech overlay without playing audio:

```bash
WAV=/absolute/path/to/speech.wav
ID="manual-$(date +%s%N)"

./bin/jarvis-head emit speak \
  --wav "$WAV" \
  --playback-id "$ID" \
  --t0 "$(date +%s.%N)"

# Optional: end it early. Otherwise WAV duration + slack ends it.
./bin/jarvis-head emit speak_end --playback-id "$ID" --ok true
```

### Exercise the live Phase 4 hooks

With the head already running, these commands generate and play real TTS while driving the mouth. They use the configured provider and may make a billable API request when the phrase is not cached.

```bash
JARVIS_HEAD_ENABLED=true ./bin/say-status.sh "Jarvis Head cloud test" true
JARVIS_HEAD_ENABLED=true ./bin/say-status-local.sh "Jarvis Head local test" true
```

For a full wake test, stop any existing wake listener first so two processes do not compete for the microphone, then start one manually:

```bash
JARVIS_HEAD_ENABLED=true ./bin/wake-jarvis.py
JARVIS_HEAD_ENABLED=true ./bin/wake-jarvis-local.py  # local alternative; do not run both
```

### Runtime overrides

```bash
# Keep listen/think visible for five minutes instead of the 120-second default.
JARVIS_HEAD_IDLE_TIMEOUT=300 ./bin/jarvis-head --cell-aspect 0.4

# Show bounded publisher failures while testing.
JARVIS_HEAD_ENABLED=true JARVIS_HEAD_DEBUG=true ./bin/jarvis-head emit listen

# Use one explicit private socket directory in every participating terminal.
install -d -m 700 /tmp/jarvis-head-manual
export JARVIS_HEAD_SOCKET=/tmp/jarvis-head-manual/head.sock
```

When overriding the socket, export the same `JARVIS_HEAD_SOCKET` before starting the display and before running emit, TTS, or wake commands.

## Tests

CI has no TTY worth driving curses on. Do not add Playwright. Do not call real `aplay` in unit tests. Extend the existing fake-`aplay` pattern in `tests/test_tts_playback_scripts.py` for the lock/emit shell test.

Required:

- `rain.py` fixed-seed column lifecycle/reset behavior, resize bounds, and separate reference/kiosk presets
- `mask.py` resize, zero-outside-head, cell-aspect correction on a tiny fixture PNG
- `visemes.py` envelope length vs wav duration, including a 200ms leading pad
- `head_events.emit` when the socket is missing (no exception, no hang)
- `head_events.emit` is nonblocking when the receiver is stale or unavailable; send failures are silent unless debug is enabled
- Round-trip with a bound test socket
- A second display cannot steal an active socket; an owned stale socket is recovered after the singleton lock is free; regular files and symlinks are never unlinked
- State transitions: `speak` from `SLEEP` (face then rain); `speak` from `LISTEN` (face stays); `sleep` changes the base without cancelling active speech; retry `playback_id`; stale `speak` / `speak_end`; missing wav; non-wav path; oversized / malformed datagram
- Idle timeout forces `SLEEP` after a listen with no further events
- Shell test: `jarvis_tts_play_audio` holds flock, **then** emit `speak`, then fake `aplay`; a second waiter does not see `speak` until the lock is held
- Shell test: disabled mode never invokes the emitter; emitter failure before/after fake `aplay` cannot suppress playback, change its exit status, or prevent retry
- Kiosk shell tests: transient unit is manual and bounded; `tty1` and active gettys are refused; stop uses the unit control group; session exit restores the captured VT
- Wake tests: normal re-arm, voice exit, exception, and Ctrl+C/finally paths all leave the display's base state at `SLEEP`

## What not to copy from the old talking-head notes

`docs/personal/talking-head/README.md` (Dec 2025, gitignored) recommended a web kiosk, Live2D, VRM, SadTalker. That path looked cheap on a flat panel. This doc replaces it for v1. Keep the personal folder for stills and private notes.

## Implementation notes when coding

- Python 3.12 annotations; `get_config_value` not raw `os.environ.get` for Jarvis keys.
- Version: do not hardcode; unused in the display besides an optional startup line from `lib/version.py`.
- Emit is silent by default. `JARVIS_HEAD_DEBUG=true` may log bounded diagnostics; never log phrase text or spam every status event.
- Wake scripts renew `listen` while their Q&A child is alive, then emit `sleep` on normal re-arm, before the voice-exit return, and from `main()` cleanup so a clean shutdown does not wait for the idle timeout.
- Run curses through `curses.wrapper`; use `finally` for socket/lock cleanup. An unexpected render exception restores the terminal and exits only the head process.
- `stdscr.nodelay(1)` already exists in matrix-crypto; keep nonblocking input, use monotonic frame pacing, and do not require its original 10ms sleep. Resize: rebuild columns and rescale mask.
- Origin comment at the top of `rain.py` points at matrix-crypto and records the source commit. Same author; no additional license plumbing is needed in Jarvis.
