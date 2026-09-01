# Jarvis Head (matrix kiosk)

**Status:** Phases 0–3 accepted. Phase 4 is implemented and automated/fake-playback verified; live wake/TTS visual acceptance is pending. Phase 5 remains design only. Optional host display, not part of install or Docker.

**Startup policy:** Manual only for v1, including Phase 5. Nothing starts the head from an existing tmux session, `start-all`, the Jarvis dashboard, an installer, systemd, or the wake process. Hooks only send optional datagrams; they never launch or supervise the display. Phase 5 packages placement as one manual kiosk command; it does not add autostart.

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
lib/head_events.py           # fire-and-forget Unix datagram send
jarvis-head/                 # application directory (not a Python package)
  app.py                     # curses loop + nonblocking event polling
  head_protocol.py           # bounded JSON validation
  head_socket.py             # singleton lock + secure datagram lifecycle
  head_state.py              # base state + speech overlay
  rain.py                    # MatrixColumn, adapted from matrix-crypto
  mask.py                    # authored masks → cell intensities (aspect-corrected)
  visemes.py                 # wav → mouth timeline (four-aperture envelope first)
  kiosk.sh                   # launch terminal with a stable app id; compositor places it
  assets/
    face.png                 # authored semantic mask: 0 outside the head
    face-blink.png           # authored eyes-closed control
    mouth-rest.png           # authored four-aperture controls
    mouth-ae.png
    mouth-o.png
    mouth-closed.png
```

Phase 0–3 commands implemented now:

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

Default path: `$XDG_RUNTIME_DIR/jarvis/head.sock` if `XDG_RUNTIME_DIR` is set, else `/tmp/jarvis-head-$UID/head.sock` (compute the uid with `os.getuid()`, not an assumed exported `$UID`). Override with `JARVIS_HEAD_SOCKET`.

For either default, create the leaf runtime directory mode `0700`; socket mode `0600`. For a custom path, do not chmod an arbitrary existing parent directory: require a safe writable parent or create only the missing leaf directory.

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

## Dedicated monitor (compositor places the window)

Wake tmux and the head do not share a terminal.

`DISPLAY=:0` names an X server, not a panel. `foot` is Wayland-oriented. Kitty documents that explicit OS-window positioning does not work on Wayland and may be ignored elsewhere. The kiosk script must **not** try to move or resize onto an output.

Launch a terminal with a **stable window class / app id** (for example kitty `--class` / `--app-id` `jarvis-head`). Pin that class to the dedicated output in the compositor or window manager the host already runs (Hyprland workspace rule, Sway output, KWin window rule, etc.). Hide the cursor inside curses (`curs_set(0)`). Opaque background.

If the panel is a raw Linux VT, skip the GUI terminal and run `bin/jarvis-head` on that tty. Same binary.

For v1, start the head yourself. Do not add it to existing Jarvis tmux sessions, `start-all`, the dashboard, or systemd. Phase 5 may add a separate manual kiosk launcher that opens the dedicated terminal on the configured output, but it must not add boot or login autostart.

## Config keys (examples only; add to env examples in Phase 5)

Add commented keys to `config/cloud.env.example` and `config/local.env.example`:

```bash
# Optional matrix face kiosk on a host monitor. Emit is a no-op unless enabled
# and bin/jarvis-head is bound to the socket.
# JARVIS_HEAD_ENABLED=false
# JARVIS_HEAD_SOCKET=   # default: $XDG_RUNTIME_DIR/jarvis/head.sock or /tmp/jarvis-head-$UID/head.sock
# JARVIS_HEAD_TERM=kitty
# JARVIS_HEAD_APP_ID=jarvis-head
# JARVIS_HEAD_COLOR=green
# JARVIS_HEAD_CELL_ASPECT=0.4
# JARVIS_HEAD_IDLE_TIMEOUT=120
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
| 5 | Manual `kiosk.sh` + compositor window rule + env keys | One explicit command opens a fullscreen, opaque head window on the dedicated output; closing it returns the monitor to the desktop. No tmux, boot, login, service, or `start-all` integration |

Phase 0 automated verification (2026-09-01): fixed-seed model tests pass; ruff passes; kiosk `q` exit and reference Ctrl+C exit both returned 0 in a 200×50 pseudo-TTY. At 30 FPS that harness measured approximately 13% CPU and 16 MiB RSS. The dedicated host monitor was visually accepted; Termius is known to wash out the black background and is not the acceptance target.

Phase 1 automated verification (2026-09-01): the authored grayscale mask is fitted from its active silhouette rather than its square image canvas, terminal cell width/height is corrected with the panel-accepted default of `0.4`, and resize rebuilds the fitted mask. Unit tests cover aspect fitting, zero-valued exterior, non-rectangular coverage, eye-highlight range, an internal dark aperture, and deterministic scattered glyph mutation. In a paired 200×50 pseudo-TTY sample at 30 FPS, rain-only used about 21% of one CPU core and the face used about 22%, with roughly 22 MiB RSS; `q`, Ctrl+C, and live resize all exited cleanly and restored the cursor. The dedicated-panel face and glyph motion were accepted before Phase 2.

Phase 2 automated verification (2026-09-01): 21 focused Phase 0–2 tests pass and cover expression-region isolation, glyph preservation across expression swaps, fixed-seed blink/drift, two-cell motion bounds, demo looping, four-aperture quantization, invalid WAVs, and file/duration limits. In 200×50 pseudo-TTY smoke tests, blink/drift and WAV-mouth demos used about 22% of one CPU core; lazy audio imports kept face-only RSS near 26 MiB, while the NumPy-backed WAV demo peaked near 40 MiB. `q`, Ctrl+C, and live resize exited cleanly and restored the cursor. Blink, drift, dynamic face glyphs, and WAV mouth motion were accepted on the dedicated panel before Phase 3.

Phase 3 automated verification (2026-09-01): 44 focused Phase 0–3 tests pass, including disabled and unavailable publishers, nonblocking queue failure, debug-only diagnostics, a real datagram round-trip, bounded malformed input, singleton refusal, owned stale-socket recovery, file/symlink protection, private modes, speech from sleep/listen, sleep during speech, retry and stale ids, invalid WAVs, idle timeout, and duration fallback. A full pseudo-TTY smoke sequence sent `listen`, `think`, `speak` with a real cached status WAV, matching `speak_end`, and `sleep`; every emit and the display returned 0 without playing audio, and the socket was removed. A separate SIGTERM run also returned 0 and removed its socket. No TTS, wake, playback-lock, or `aplay` path is changed in this phase.

Phase 4 automated verification (2026-09-01): 64 focused Phase 0–4 tests pass. The wake and playback test files also pass in both collection orders, proving their standard-library mocks are restored between tests. Shell tests prove disabled mode never invokes the emitter; each retry emits a unique id after the playback lock, followed by a matching success/failure end; terminating a blocked playback process group emits its matching failed end; a queued waiter emits nothing until it owns the lock; and an emitter failure cannot change retry count or playback success. Behavioral cloud/local wake tests cover normal re-arm, voice exit, question-process failure, long-Q&A keepalive, Ctrl+C, and startup failure, with every path returning the head to `SLEEP`. A pseudo-TTY display accepted the real emitter around a real cached WAV while a fake `aplay` returned success; no audio played, both processes returned 0, and the socket was cleaned up. The face palette test keeps all mask intensities in the selected color while reserving white for rain leads. No startup, tmux, dashboard, installer, or service file is changed.

Optional later: Rhubarb vs envelope side-by-side. Hook `question.sh` / `question-local.sh` / `question-mic.sh` only if those leftover `aplay` paths still matter.

## Manual command reference

Run these from the repository root. The head always starts manually; emit, TTS, and wake commands never launch it.

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
