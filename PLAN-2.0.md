# treemap 2.0: plan and roadmap

**Goal:** make treemap comfortable for someone who isn't its author. They install one
server, open a web page on their phone, scan their tree, and then pick effects from the
same page or from Home Assistant. No IP Webcam app, no terminal, no config file to edit.

1.x proved the hard parts: the colour-code scan, the 3D and flat solves, the effects
engine and the WLED output all work. 2.0 changes **where things run and how the user
gets through them**. It doesn't change the algorithms.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where does the scan UI run? | A **static web page on HTTPS**, hosted on **Cloudflare Pages**, opened on the phone. | The phone camera (`getUserMedia`) needs a secure page. A hosted page gets HTTPS for free, so the self-hosted server needs no certificate. |
| Who talks to WLED? | **Only the server**, over DDP as now. The phone never talks to WLED. | Browsers can't send UDP, and the server already streams DDP reliably. |
| How does the HTTPS page reach a plain-HTTP server on the LAN? | Chrome's **Local Network Access** permission. A `fetch()` to a private IP or a `.local` name is exempt from mixed-content blocking once the user allows it. | No certificate on the server. |
| Which browsers? | **Android Chrome only** for scanning. | It's also the only browser that lets a page lock the camera's exposure and white balance. iOS Safari can't. |
| Where does solving run? | **On the server**, in the existing Python code. | It's tested and runs as it is; it takes the same time on every phone; the rounds are kept, so a scan can be solved again after a solver fix. Video is only 2–4 MB/s even at 720p, trivial for home Wi-Fi. |
| Who runs the scan? | **The phone.** It calls the server step by step: LEDs white, try this exposure, show red, start a round, and so on. | The user holds the phone, so every prompt and decision belongs on its screen. |
| Effects UI | **On the server's own page** (revised 2026-11-22), with the devices, their LEDs in 3D and a QR code per device. The hosted scan page only scans. | The server's page is where the devices live, and it can show and preview effects in 3D; the scan page stays small and phone-only. |
| Scope | **One server drives several devices** (revised 2026-11-22). Each device is one WLED controller with its own LEDs, map, scans and effects. | The real tree and a virtual one (or a tree and a window) can run side by side. A tree split over two controllers isn't covered yet. |
| Devices | **Added on the server's page by address; nothing in the config.** Kept in `data/devices.json`; the first run has none. Each LED count is read from WLED once and kept. | No config file to edit. A device that's off stays on the list: its map shows, and effects preview on the page. |
| Map history | **None: only the current map,** per device. A new scan replaces it, and its rounds replace the old rounds. | Nothing to manage or clean up. Rounds are still kept until the next scan, so the current scan can be solved again. |
| Home Assistant | **MQTT discovery.** The server announces a light whose effect list is your favourites, and a select entity for playlists. | Home Assistant creates the entities itself: no custom integration to write or keep up to date. |

## How it fits together

```
 Phone (Android Chrome)                 Server (Python, on the LAN)           WLED
 ┌──────────────────────────┐  fetch   ┌───────────────────────────┐  DDP   ┌────────┐
 │ hosted HTTPS page        │ ───────▶ │ HTTP API (+ CORS)         │ ─────▶ │ ESP32s │
 │ - setup, wiring check    │  frames  │ - LED commands            │        └────────┘
 │ - camera, exposure lock  │ ◀─────── │ - scan rounds, decode,    │
 │ - scan progress          │  status  │   solve (existing code)   │  MQTT  ┌────────┐
 │ - front / bottom         │          │ - effects, favourites,    │ ─────▶ │ Home   │
 │ - effects, favourites,   │          │   playlists               │        │ Assist.│
 │   playlists              │          │ - tree_map.json, rounds   │        └────────┘
 └──────────────────────────┘          └───────────────────────────┘
```

### The user's flow

1. **Install** the server: Docker, or a Home Assistant add-on.
2. **Add the controller** on the server's page (`http://<server>:8765/`) by its address.
3. **Open the scan page** from the device's QR code on the server's page: a link like
   `https://<project>.pages.dev/?server=http://192.168.1.20:8765&device=<id>`.
   Chrome asks for the local network permission once. Pick **tree** or **flat**.
4. **Check the wiring:** the page runs the chase and asks "did the light run from the
   start of strip 1 to the end?".
5. **Scan:**
   1. LEDs glow white; point the camera at them.
   2. Exposure: the page tries exposures (shortest first) while the server counts the
      LEDs it sees in the uploaded frames, and keeps the shortest that sees nearly all.
      Phones without manual exposure: let auto-exposure settle, then lock it.
   3. Colours: the LEDs show red, green, blue and white in turn; the server measures how
      this phone sees each colour (today's `camera check`).
   4. Rounds: the LEDs flash their codes while the user walks round; after each round
      the server shows the status colours on the tree and the page shows the counts.
6. **Review:** fix red LEDs (scan that part again, or interpolate). Then set the
   **front** (tree) or **bottom** (flat), see below. Save.
7. **Enjoy:** effects, favourites and playlists on the page, or from Home Assistant.

### Setting the front and the bottom (new)

Today the map's "front" is wherever the scan started, and a flat map's "up" is the top
of the phone's picture. 2.0 lets the user set them on the real LEDs:

- **Tree:** the server lights a vertical stripe at the current front angle; the user drags
  a slider until the stripe faces the room.
- **Flat:** the server lights the current bottom edge; the user turns it, in 90° steps or
  by any angle for strips laid askew (plus a mirror switch, in case the strips were
  filmed from behind).

Both can be set from the scan page's Review screen or from the device on the server's
page.

The map keeps its solved positions and stores the orientation alongside them
(`orientation: {front_deg}` or `{rotate_deg, mirror}`), so it can be changed later
without scanning again. `Geometry.of` applies it, so every effect picks it up.

## The server API (first sketch)

Now `/api/v2`, with every device endpoint under `/devices/{id}` (Phase 6b); the
modules' docstrings have the current list. The first sketch:

All under `/api/v1`, JSON unless noted. Every response carries CORS headers for the
hosted page's origin (configurable), and `OPTIONS` preflights are answered.

| Method and path | What it does |
|---|---|
| `GET /info` | API version, server version, the WLED controllers and their LED counts, current map summary. The page refuses to go on if the API version doesn't match. |
| `POST /leds` | `{mode: off \| white \| solid \| chase \| led \| code \| status \| stripe \| edge, ...}` |
| `POST /scan/start`, `POST /scan/stop` | Start or stop a scan session (`shape: tree \| flat`, `symbol_ms`, `brightness`). |
| `POST /scan/frames` | A batch of frames, body `application/octet-stream`: the same wire format as `BrowserCamera` today (header length, JSON header, JPEG), repeated. Sent every ~250 ms. |
| `GET /scan/state` | Phase, round, time left, LEDs identified, per-status counts, per-LED status after a round. Polled about once a second. |
| `POST /scan/exposure-probe` | "Count the LEDs in the frames since t." Answers the phone's exposure search. |
| `POST /map/orientation` | Set front / bottom. |
| `GET /effects` | Effects with their parameters (name, type, range, default), so the page builds its controls from data. |
| `POST /play` | Play an effect with parameters, a favourite or a playlist. |
| `GET/PUT/DELETE /favourites[/id]`, `/playlists[/id]` | Stored on the server (today: in the browser's localStorage). |

Rules for the page: `fetch()` only, no WebSockets (Chrome's permission doesn't cover them
reliably yet); reach the server by IP or a `.local` name (any other name needs
`targetAddressSpace: "local"` on every fetch). **Every fetch comes from the page's main
thread:** a worker's fetches to the LAN fail even with the permission granted (spike 1.1).
Workers encode, then hand the batch to the page to send.

Camera rules (spike 1.2): pick the rear camera with continuous focus, because
`facingMode: "environment"` can give a fixed-focus wide lens. Lock white balance by
setting a `colorTemperature` (Chrome snaps it to a preset); `whiteBalanceMode: "manual"`
alone is ignored. Chrome reads manual exposure back as `exposureMode: "none"`.
`exposureTime` is in 100 µs units.

## What stays, what goes

- **Stays:** `scan/` (decode, solve, cleanup), `mapping/`, `effects/`, `engine.py`,
  `outputs/` (DDP), `workflow.py`, and the tree and flat generators (now the virtual
  WLED's, and the scan tests' ground truth).
- **Gone** (2026-11-23, see [Phase 6c](#phase-6c-the-1x-commands-and-the-viewer-go)): the
  1.x command line and the simulator's 3D viewer, with what only they used: the IP
  Webcam camera, the viewer's virtual phone and output, the config's `output`,
  `controllers`, `camera` and `sim`.
- **New:** an `HttpCamera` (frames arrive on `POST /scan/frames` and feed the same
  `Camera` interface the 1.x cameras did), the API layer, the scan page, MQTT.

## Risks

- **Local Network Access behaves differently than expected** on the user's Chrome
  version. Proved on Chrome 157 (step 1.1), except from workers (see the rules above).
- **Camera controls vary by phone.** The page must read `getCapabilities()` and fall back
  to auto-then-lock. The S23 has full manual exposure, ISO and focus (step 1.2).
- **JPEG encoding at 720p, 24 fps** in the browser may be heavy. Settled: in a worker
  with `OffscreenCanvas`, it takes 22 ms a frame on the S23 with no drops (step 1.3).
- **The hosted page and a user's server drift apart** in version. The `/info` handshake
  catches it; the server also serves its own matching copy of the page.
- **The hosted page needs the internet to load.** Make it a PWA so it opens offline after
  the first visit.

---

# Roadmap

Small steps, each finished and testable on its own. Phase 1 proves the risky parts
before anything is built on them.

## Phase 1: prove the risky parts (throwaway spikes)

**Done** (2026-11-21, Galaxy S23, Chrome 157). Code and full results are in
[spikes/phase1/](spikes/phase1/README.md); the page is at https://treemap-spike.pages.dev/.
All three work, with these changes to the plan (now in the rules and risks above):
fetches come only from the page, never from a worker; the page picks the main camera
itself; white balance is locked through a `colorTemperature` preset. 720p uploads at
24 fps and 2.4 MB/s with a smooth preview.

- **1.1 Local network from HTTPS.** A one-file page on Cloudflare Pages that `fetch()`es
  `http://<mac-ip>:8765/ping` from your phone.
  **Done when:** Chrome shows the permission prompt and the response arrives.
- **1.2 Camera controls.** The same page prints `track.getCapabilities()` and tries manual
  exposure, ISO, white balance and focus.
  **Done when:** you know which of these your phone supports, with their ranges.
- **1.3 Frame upload.** The page encodes 640×480 and 720p JPEGs in a worker and POSTs
  them in 250 ms batches to a dummy endpoint.
  **Done when:** you have measured fps and MB/s for both sizes, with the preview smooth.

## Phase 2: server foundations

**Built** (2026-11-21): `treemap serve` ([treemap/api/](treemap/api/)), on the standard
library's threaded HTTP server; `HttpCamera` ([treemap/cameras/http.py](treemap/cameras/http.py));
controllers with only a host; engine timing. Tested on this Mac, with the simulated LEDs
and a stand-in phone that uploads rendered frames. Still to check on the real tree:
2.2 from the phone (`https://treemap-spike.pages.dev/?server=http://<ip>:8765&ping=/api/v1/info`),
2.3 chase on the LEDs, 2.5 with only the host, 2.5b stutter (effects speed up and slow
down on the real LEDs; the timing on the server's page now tells where). Changes from the sketch:
`POST /play` already runs an effect (Phase 6 added favourites and playlists); a frame
batch is each frame with a 4-byte length in front; `/scan/state` gives each LED's
status as one letter (o, i, f).

- **2.1 `treemap serve`.** A server command that listens on the LAN (`0.0.0.0`) without
  the simulator, with `GET /api/v1/info`.
  **Done when:** `curl http://<ip>:8765/api/v1/info` works from another machine.
- **2.2 CORS and versioning.** Allowed origins in `config.yaml` (default: the hosted page
  and `localhost` for development), preflights answered, the API version in `/info`.
  **Done when:** spike 1.1's page reads `/info` from the real server.
- **2.3 LED commands.** `POST /leds` for off, white, solid, chase, led N.
  **Done when:** `treemap test chase` and a `curl` do the same thing.
- **2.4 `HttpCamera`.** `POST /scan/frames` fills a queue behind the `Camera` interface.
  **Done when:** a test script that uploads saved frames gets them decoded by a scan
  round, the same way as through `BrowserCamera`.
- **2.5 Simpler controller config.** Keep the `controllers:` list, but only the host
  is required: read each controller's LED count from WLED's `/json/info` and lay them
  out in order. `start`, `count` and `reverse` stay as optional overrides.
  **Done when:** the server starts with only the hosts configured.
- **2.5b Frame timing.** Measure render time, send time and frames that fell behind;
  show them in `/info` and warn when the engine can't keep its frame rate. Check WLED's
  "Disable WiFi sleep" in `treemap wled check` (gone with the 1.x commands in Phase 6c;
  not on the server's page yet).
  **Done when:** effects run without visible stutter on 400 LEDs, and the numbers show why
  if they don't.
  Since 2026-11-23 the timing also has the gap from one frame to the next (`gap_ms`),
  which shows the server pausing between frames, and the server's page shows it all under
  Now playing (fps, gaps, render, send, late) with a verdict: can't keep up, paused, or
  steady. Steady while the LEDs still speed up and slow down means the frames are held
  up on the Wi-Fi or in the controller: on a Mac, AirDrop's AWDL radio (`sudo ifconfig
  awdl0 down` to test) or WLED's WiFi sleep. Switching to TCP, as some setups with
  thousands of LEDs do, wouldn't help: 400 LEDs are one DDP packet a frame, and TCP
  would hold later frames back behind a lost one.
- **2.6 Scan sessions over HTTP.** `scan/start`, `scan/stop`, `scan/state`, wired to
  `workflow.py`. Status colours after each round as now.
  **Done when:** the simulator's virtual phone can scan through the HTTP endpoints
  instead of the camera WebSocket.

## Phase 3: scan page, first usable version

**Built** (2026-11-21): [scanapp/](scanapp/), screens for connect, wiring check and scan.
Tested on this Mac in headless Chrome 157 with its fake camera against `treemap serve
--sim`: chase and single LED, countdown, rounds, results and Stop all work, and 20–22 fps
uploads with no bad frames. The fake camera shows no LEDs, so nothing was identified.
Deployed by hand to **https://treemap-scan.pages.dev/** (Cloudflare Pages project
`treemap-scan`, direct upload: `npm --prefix scanapp run build && wrangler pages deploy
scanapp/dist --project-name treemap-scan --branch main`); not yet on every push. Still to
check on the phone: 3.1 from the hosted page, and 3.4's flat scan. Changes from the sketch: `/scan/state` sends `led_status`
and `counts` after a stopped or finished scan too, but only for a map that scan made.

- **3.1 Project setup.** A new `scanapp/` (Vite + Svelte + TypeScript, like the viewer),
  deployed to Cloudflare Pages on every push. Reads `?server=` and remembers it.
  **Done when:** the page loads from Cloudflare Pages and shows the server's `/info`.
- **3.2 Setup screen.** Server address, tree or flat, a clear message for the wrong
  browser or a mismatched API version.
- **3.3 Wiring check screen.** Chase, then "did it run start to end?"; lighting a single
  LED by number.
- **3.4 Camera and upload.** Rear camera, full-screen preview, frames uploaded during a
  round. Auto exposure for now.
  **Done when:** a flat layout scans from the page.
- **3.5 Round progress.** Polls `scan/state`: round, time left, counts, "walk to the red
  parts". Stop and finish buttons.

## Phase 3b: a virtual WLED to scan on screen

**Built** (2026-11-21): `treemap sim wled` ([treemap/sim/virtual_wled.py](treemap/sim/virtual_wled.py),
page `web/wled.html`, `viewer/wled.html` until Phase 6c). This computer acts as a WLED
controller with a simulated tree or flat layout ([treemap/sim/flat.py](treemap/sim/flat.py): rows or a spiral) on its
screen, so the whole 2.0 path can be tried with only a phone, and Phase 4's exposure and
colours can be tuned on it. `treemap serve` drives it unchanged (`output: wled`, a
controller `host` with the HTTP port). You walk round it with the viewer's walk keys
while the phone films the screen. Tested on this Mac: `serve` read its LED count and
streamed effects at 40 fps; the page shows them, walks, and makes new layouts.

- **3b.1 Virtual controller.** DDP on UDP 4048; `/json`, `/json/info`, `/json/state`,
  `/json/cfg` as WLED answers them; dark after 2.5 s without frames, as WLED.
- **3b.2 Flat layouts.** Strips joined end to end in rows or a spiral, hand-laid wobble,
  rows far enough apart for a camera to separate.
- **3b.3 The screen.** Full screen, lit as the virtual phone sees the tree; walk keys; a
  panel (hidden while walking) with the config lines and new layouts.
  **Done when:** a flat and a tree layout scan from the phone pointed at the screen.
  Not checked yet. Filming a screen adds a second projection: square-on and centred it
  acts as one camera with another focal length, which the solve estimates; at an angle
  the picture is skewed, which it doesn't model.

## Phase 4: exposure and colours from the phone

**Built** (2026-11-21, revised 2026-11-22 after a first try on the virtual WLED). A scan
started with `camera` (the phone's model and camera label) gets two new phases after the
countdown. In **exposure**, the LEDs show the code's colours along the strip (red, green,
blue, white, …) at the scan's brightness while the page runs its search
([scanapp/src/lib/exposure.ts](scanapp/src/lib/exposure.ts)), then lets the user tap
another exposure to try it, and calls `POST /scan/camera-ready` when the user taps
Continue. The server gives up after 5 minutes. In **colours**, the server runs the
existing colour check on the uploaded frames and saves the result to
`data/camera_colours/<phone>.json`. `/scan/state` then has `colours`: the share read
right per colour, whether all pass, and tips. Changes from the sketch:
- `exposure-probe` takes `{since, frames}`, and `since` is on the frames' own clock. The
  encoder worker reports the newest frame's time (`mark`), so frames taken before a
  change aren't counted.
- **The search judges exposures on the code's colours, not white.** The first try picked
  8 ms with all LEDs white: 199 LEDs seen in white but 16 in blue, so every code broke
  and no LED was read. It now climbs 0.5–8 ms at ISO 100, then ISO 200–1600 at 8 ms (not
  longer, which would smear while walking), stops after two steps in a row that add
  under 5%, and keeps the darkest within 95% of the best. "The best", not "all": far-side
  LEDs never show. The second try climbed to ISO 1600, where the phone saw about 2,200
  spots on a 400-LED tree (lit branches, noise) and rounds read only 26–92 LEDs. So a step
  that sees more spots than there are LEDs, or lights over 15% of the picture
  (`exposure-probe` also returns `lit`), is too bright: the climb stops and it's never
  picked.
- **Manual override:** a strip of the exposures from darker to brighter, each with a bar
  of the LEDs it saw, the automatic pick tagged; tapping one sets and counts it. The
  start screen can reuse the exposure last kept with this camera instead of searching.
  The colours file keeps the search's counts.
- **Rounds start when the user says** (`POST /scan/next`, `waiting` in the state): after
  each round but the last, the LEDs show the result until the user, standing where it's
  red, taps Start round N, or Finish here. The server waits up to 15 minutes, then
  finishes with what it has. A round too sparse to solve shows the LEDs read so far
  yellow and the rest red, instead of going dark.
- The page can disconnect from the server, which also stops it reconnecting on reload.
- The colour check waits 1 s after each change instead of 0.6 s, because frames from the
  page arrive in batches, and flags a colour seen in under 70% as many LEDs as white.
Still to check on the phone: 4.3's 85% bar.

- **4.1 Exposure probe.** `POST /scan/exposure-probe` counts the LEDs in recent frames.
- **4.2 Exposure search on the page.** Darkest exposure first; keep the darkest that sees
  nearly as many LEDs as the best, with a manual override. Fallback: auto, settle, lock.
- **4.3 Colour measurement.** White, red, green, blue in turn; the server stores the
  result per phone (by its camera label), as `camera_colours.json` today.
  **Done when:** the colour check passes the 85% bar on your phone, started from the page.

## Phase 5: review, front and bottom

**Built** (2026-11-22): the page's **Review** screen ([scanapp/src/screens/Review.svelte](scanapp/src/screens/Review.svelte)),
opened after a scan or from the connect screen. Not yet tried on the phone. Changes from the sketch:
- Each solve picks its own heading, so solving again (a fix, or more rounds) first turns
  the new positions onto the old map's, using the LEDs ok in both, then keeps its
  orientation (`follow` in [treemap/scan/free.py](treemap/scan/free.py)). A fresh scan resets it.
- The flat orientation is a mirror, then a turn anticlockwise, and the map is
  normalised again (y 0–1) after turning. The turn was quarter turns only at first;
  since 2026-11-23 it's any angle (to a tenth of a degree), with a slider beside the
  quarter turns.
- Since 2026-11-23 the server's page sets the front or the bottom too, on each device
  with a map ([web/src/server/OrientationCard.svelte](web/src/server/OrientationCard.svelte)):
  the same stripe or edge on the LEDs while it's set, shown in the 3D view as well.
- `edge` lights the bottom edge white and the left side red, so the mirror can be checked.
- Ignoring an LED's readings only helps a *misplaced* LED: a red one has no readings to
  drop. So red and yellow runs light blue and offer "scan this part again"
  (`scan/start` with `add`, which keeps the rounds so far), and a separate card ignores a
  misplaced LED's readings (`POST /map/interpolate`), found with a rising plane.
- New: `GET /map`; `led` mode takes `to` and `neighbours`.

- **5.1 Map format v2.** `orientation` alongside the positions; `Geometry.of` applies it;
  v1 maps still load (orientation 0).
- **5.2 Stripe and edge LED modes** on the server.
- **5.3 Front slider (tree) and turns plus mirror (flat)** on the page.
  **Done when:** a "plane around" effect starts at the front you set.
- **5.4 Fixing LEDs on the page.** A list of red and yellow LEDs; tap one to light it blue;
  interpolate, or scan that area again.

## Phase 6: effects on the page

**Built** (2026-11-22): an **Effects** screen, first on the scan page, then moved to the
server's own page in Phase 6b ([web/src/server/EffectsPanel.svelte](web/src/server/EffectsPanel.svelte)); favourites and playlists in `data/library.json`
([treemap/library.py](treemap/library.py)), played by [treemap/player.py](treemap/player.py).
Tested through the API on this Mac; not yet tried on the phone. Changes from the sketch:
- `GET /effects` leaves out the test patterns and scan views (Diagnostics, Mapping) and
  says which effects `needs_map`; the page greys those out without a map.
- `GET /play` says what's playing: the effect and its settings, the brightness, the
  favourite last started and the playlist (which item, seconds to the next). New:
  `POST /play/params` (tune live), `POST /play/next`, `POST /brightness`, `POST /stop`.
- A favourite stores every parameter, so the page can tell what's playing is one, or
  "changed from" one (Update it). A playlist is `{name, items: [{favourite,
  duration_s}], crossfade_s, shuffle}`; it loops, picks up edits each round, skips
  favourites that can't play, and ends when anything else is played. Deleting a
  favourite takes it out of playlists.
- **The viewer keeps its favourites on its server too** (same file, over its websocket),
  so the "one-time import" is automatic: the first time it connects it hands over what
  it kept in localStorage (stale settings get defaults, duplicates are skipped). Gone
  with the viewer in Phase 6c, `POST /favourites/import` too.
- The brightness isn't saved: it's back to `engine.brightness` after a restart (Phase 7's
  light entity may want that).

- **6.1 Effect parameters as data.** `GET /effects` describes each effect's parameters.
- **6.2 Effects screen.** Pick, tune, brightness, stop. Generated from 6.1.
- **6.3 Favourites on the server.** Move them from localStorage, with a one-time import
  from the viewer.
- **6.4 Playlists.** A list of favourites with durations and crossfades (1.x Batch 7).

## Phase 6b: devices and the server's page

**Built** (2026-11-22). `treemap serve` runs with no controllers configured and keeps
running while they're off. Its page ([web/src/server/](web/src/server/), built
into `treemap/web_dist/server.html`; `viewer/` and `treemap/sim/viewer_dist/` until
Phase 6c) lists the devices, adds one
by address, and shows each with:
- whether its controller answers (the server asks each one's `/json/info` every 5 s),
  its WLED name, version and LED count, and a warning with a fix when WLED's count changes;
- a **QR code** for the scan page with `?server=…&device=<id>`;
- its LEDs **in 3D** where the scan placed them, lit with the frames the server sends it
  (fetched about 20 times a second);
- its **effects** (Phase 6's screen, moved from the scan page), with **Send to the
  LEDs** off to preview an effect on the page only. A device that's off works the same
  way: effects play on the page.

Changes:
- **API v2.** Every device endpoint is under `/api/v2/devices/{id}` (see
  [treemap/api/device.py](treemap/api/device.py)); the server's own are `/info`,
  `/devices`, `/effects`, `/favourites`, `/playlists` ([treemap/api/app.py](treemap/api/app.py)).
  New: `GET /frame`, `POST /send`, `positions` in `GET /map`, `POST /map/adopt`.
- **Each device's data** is in `data/devices/<id>/` (map and scans). A map from before
  devices (`data/tree_map.json`) can be taken over from the device page when its LED count
  matches. Removing a device leaves its data on disk.
- **A controller is opened on a thread of its own** and again every 5 s after a failure,
  so a `.local` name that doesn't resolve never holds up the effects.
- **The virtual WLED** (`treemap sim wled`) is added like any controller, by the address
  it prints; the server sees it's virtual (its `/json/info` product) and drives it
  without the LEDs' gamma.
- **The scan page** opens on one device (from the QR code, or picked from the server's
  list) and no longer has effects. The wiring screen points at WLED's settings, not the
  config.
- **`treemap serve --sim` and `treemap sim view --serve` are gone**: the virtual WLED
  replaces them. `config.yaml`'s `output` and `controllers` are now only for the 1.x
  commands (`treemap scan`, `treemap run`, …; all gone in Phase 6c). New:
  `server.scan_page`, which the QR codes open and the server allows.
- Not covered yet: a tree split over two controllers (one device per controller for now).

Not yet tried with the phone or the real tree.

## Phase 6c: the 1.x commands and the viewer go

**Done** (2026-11-23). The server, the scan page and the virtual WLED cover everything the
1.x tools did, so these are removed, with the code only they used:

- **The command line** but for `treemap serve` and `treemap sim wled`: `scan`,
  `reconstruct`, `show-mapping`, `fix`, `run`, `effects`, `test …`, `camera check`,
  `wled check`, `sim new`, `sim view`, `sim evaluate`, `config show`.
- **The simulator's 3D viewer** (`treemap sim view`): its page, its server
  (`treemap/sim/server.py`, websockets), its virtual phone (`BrowserCamera`) and output
  (`SimOutput`), and the "true tree" map choice for effects.
- **The IP Webcam camera** (`cameras/android.py`) and the exposure search for it.
- **The effects that were test patterns or scan views** (index chase, markers, single
  LED, map status, verify sweep): `POST /leds` does those now.
- **Config keys** `output`, `controllers`, `camera` (its `fov_deg` is now
  `scan.fov_deg`), `sim` and `scan.camera_fps`. An old `config.local.yaml` still loads:
  they're ignored with a warning.
- `ROADMAP.md`, the 1.x plan.

`viewer/` is now `web/` (the server's page and the virtual WLED's screen), built into
`treemap/web_dist/`. Kept: the tree and flat generators, the scan tests that use them as
ground truth, and taking over a 1.x map (`data/tree_map.json`) from a device's page.
`treemap wled check`'s WiFi-sleep and brightness warnings aren't on the server's page yet.

## Phase 7: Home Assistant

- **7.1 MQTT connection** settings in the config; reconnect on failure.
- **7.2 Light entity** by discovery: on/off, brightness, effect list = favourites.
- **7.3 Playlist select entity.**
  **Done when:** a Home Assistant automation turns the tree on with a favourite at sunset.

## Phase 8: packaging and polish

- **8.1 Dockerfile** and a compose example.
- **8.2 Home Assistant add-on** (it can also find the MQTT broker for you).
- **8.3 QR code** in `treemap serve`'s terminal output (the server's page has one per
  device since Phase 6b).
- **8.4 PWA** manifest and service worker, so the page opens offline.
- ~~**8.5 The server serves its own copy of the page**~~ Replaced by Phase 6b: the
  server has its own page for devices and effects; the scan page is only hosted.
  Was: **The server serves its own copy of the page** over plain HTTP, for effects without
  internet and as a fallback.
- ~~**8.6 Retire IP Webcam**~~ Done in Phase 6c, with the rest of 1.x, before the browser
  camera has scanned the real tree.

## Phase 9: the real tree, end to end

Run the whole flow on the 2.5 m tree with a phone that has never been used for it before:
install, scan, set the front, play a playlist, automate from Home Assistant.
**Done when:** a rising plane looks level on the tree, and nothing needed the terminal.

## Settled

- The page is hosted on **Cloudflare Pages**.
- **One server, several devices,** each one WLED controller with its own map.
- **No map history:** a new scan replaces the device's map.
