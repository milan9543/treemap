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
| Effects UI | **In the same hosted page**, so users have one app. The server also serves the page over plain HTTP as a fallback. | One app; the server can run with no UI of its own. |
| Scope | **One server drives one tree, on one or more WLED controllers.** | 1.x already splits the LEDs across controllers, and each controller only receives its own LEDs, so more controllers add almost no load. Each controller's LED count comes from WLED itself. |
| Map history | **None: only the current map.** A new scan replaces it, and its rounds replace the old rounds. | Nothing to manage or clean up. Rounds are still kept until the next scan, so the current scan can be solved again. |
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
2. **Open the scan page** from the server: its page (and `treemap serve` in the terminal)
   shows a QR code and a link like `https://<project>.pages.dev/?server=http://192.168.1.20:8765`.
   Chrome asks for the local network permission once. Pick **tree** or **flat**.
3. **Check the wiring:** the page runs the chase and asks "did the light run from the
   start of strip 1 to the end?".
4. **Scan:**
   1. LEDs glow white; point the camera at them.
   2. Exposure: the page tries exposures (shortest first) while the server counts the
      LEDs it sees in the uploaded frames, and keeps the shortest that sees nearly all.
      Phones without manual exposure: let auto-exposure settle, then lock it.
   3. Colours: the LEDs show red, green, blue and white in turn; the server measures how
      this phone sees each colour (today's `camera check`).
   4. Rounds: the LEDs flash their codes while the user walks round; after each round
      the server shows the status colours on the tree and the page shows the counts.
5. **Review:** fix red LEDs (scan that part again, or interpolate). Then set the
   **front** (tree) or **bottom** (flat), see below. Save.
6. **Enjoy:** effects, favourites and playlists on the page, or from Home Assistant.

### Setting the front and the bottom (new)

Today the map's "front" is wherever the scan started, and a flat map's "up" is the top
of the phone's picture. 2.0 lets the user set them on the real LEDs:

- **Tree:** the server lights a vertical stripe at the current front angle; the user drags
  a slider until the stripe faces the room.
- **Flat:** the server lights the current bottom edge; the user turns it in 90° steps
  (plus a mirror switch, in case the strips were filmed from behind).

The map keeps its solved positions and stores the orientation alongside them
(`orientation: {front_deg}` or `{rotate_deg, mirror}`), so it can be changed later
without scanning again. `Geometry.of` applies it, so every effect picks it up.

## The server API (first sketch)

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
  `outputs/` (DDP), `workflow.py`, the simulator and the 3D viewer for development.
- **Goes:** `cameras/android.py` (IP Webcam) once the browser camera works on the real tree.
  Keep it until then.
- **New:** an `HttpCamera` (frames arrive on `POST /scan/frames` and feed the same
  `Camera` interface as `BrowserCamera`), the API layer, the scan page, MQTT.

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
2.3 chase on the LEDs, 2.5 with only the host, 2.5b stutter. Changes from the sketch:
`POST /play` already runs an effect (Phase 6 adds favourites and playlists); a frame
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
  "Disable WiFi sleep" in `treemap wled check`.
  **Done when:** effects run without visible stutter on 400 LEDs, and the numbers show why
  if they don't.
- **2.6 Scan sessions over HTTP.** `scan/start`, `scan/stop`, `scan/state`, wired to
  `workflow.py`. Status colours after each round as now.
  **Done when:** the simulator's virtual phone can scan through the HTTP endpoints
  instead of the camera WebSocket.

## Phase 3: scan page, first usable version

**Built** (2026-11-21): [scanapp/](scanapp/), screens for connect, wiring check and scan.
Tested on this Mac in headless Chrome 157 with its fake camera against `treemap serve
--sim`: chase and single LED, countdown, rounds, results and Stop all work, and 20–22 fps
uploads with no bad frames. The fake camera shows no LEDs, so nothing was identified.
**Not deployed yet**: `treemap-scan.pages.dev` is the intended address, already the
default origin and the link `treemap serve` prints. Still to check on the phone: 3.1 once
deployed, and 3.4's flat scan. Changes from the sketch: `/scan/state` sends `led_status`
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

## Phase 4: exposure and colours from the phone

- **4.1 Exposure probe.** `POST /scan/exposure-probe` counts the LEDs in recent frames.
- **4.2 Exposure search on the page.** Shortest exposure first; keep the shortest that sees
  nearly as many LEDs as the best. Fallback: auto, settle, lock.
- **4.3 Colour measurement.** White, red, green, blue in turn; the server stores the
  result per phone (by its camera label), as `camera_colours.json` today.
  **Done when:** the colour check passes the 85% bar on your phone, started from the page.

## Phase 5: review, front and bottom

- **5.1 Map format v2.** `orientation` alongside the positions; `Geometry.of` applies it;
  v1 maps still load (orientation 0).
- **5.2 Stripe and edge LED modes** on the server.
- **5.3 Front slider (tree) and 90° turns plus mirror (flat)** on the page.
  **Done when:** a "plane around" effect starts at the front you set.
- **5.4 Fixing LEDs on the page.** A list of red and yellow LEDs; tap one to light it blue;
  interpolate, or scan that area again.

## Phase 6: effects on the page

- **6.1 Effect parameters as data.** `GET /effects` describes each effect's parameters.
- **6.2 Effects screen.** Pick, tune, brightness, stop. Generated from 6.1.
- **6.3 Favourites on the server.** Move them from localStorage, with a one-time import
  from the viewer.
- **6.4 Playlists.** A list of favourites with durations and crossfades (1.x Batch 7).

## Phase 7: Home Assistant

- **7.1 MQTT connection** settings in the config; reconnect on failure.
- **7.2 Light entity** by discovery: on/off, brightness, effect list = favourites.
- **7.3 Playlist select entity.**
  **Done when:** a Home Assistant automation turns the tree on with a favourite at sunset.

## Phase 8: packaging and polish

- **8.1 Dockerfile** and a compose example.
- **8.2 Home Assistant add-on** (it can also find the MQTT broker for you).
- **8.3 QR code** on the server's page and in `treemap serve`.
- **8.4 PWA** manifest and service worker, so the page opens offline.
- **8.5 The server serves its own copy of the page** over plain HTTP, for effects without
  internet and as a fallback.
- **8.6 Retire IP Webcam** (`cameras/android.py`) once the browser camera has scanned the
  real tree.

## Phase 9: the real tree, end to end

Run the whole flow on the 2.5 m tree with a phone that has never been used for it before:
install, scan, set the front, play a playlist, automate from Home Assistant.
**Done when:** a rising plane looks level on the tree, and nothing needed the terminal.

## Settled

- The page is hosted on **Cloudflare Pages**.
- **One server, one tree,** on one or more WLED controllers.
- **No map history:** a new scan replaces the map.
