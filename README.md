# treemap

Map where each LED of a WLED Christmas tree really is, using a phone camera, then run
effects that use those 3D positions: a plane sweeping up the tree, a rainbow turning
round it, and so on. LEDs laid flat (on the floor, or taped to a wall) map in 2D the
same way.

Scanning works like this: every LED flashes its own colour code at once while you walk
round the tree filming it with the phone. After each round of about 12 seconds, the tree
lights up green where LEDs are placed, yellow where they were filled in from their
neighbours, and red where they're still unknown. Walk to the red parts and the next round
fills them in.

It runs on a **server** on your network and a **page on the phone**: you add your WLED
controllers on the server's web page, scan each one from the phone, and play effects
from the server's page. Without real LEDs yet, a **virtual WLED** puts a simulated tree
on this computer's screen for the phone to scan. See [PLAN-2.0.md](PLAN-2.0.md) for the
plan and what's next.

> **Status:** built: the server with several devices and its page, the scan page
> (wiring, exposure and colours, rounds, review with front and bottom), effects,
> favourites and playlists, and the virtual WLED. Tested on this Mac, not yet with the
> phone or the real tree. A flat layout has been scanned on real LEDs with the earlier
> command-line version. Still to come: Home Assistant (MQTT), Docker and the add-on, the
> offline scan page.

## Install

You need [uv](https://docs.astral.sh/uv/), Python 3.11 or newer, and Node.js 20.19+ or
22.12+ to build the web pages.

```sh
uv sync
npm --prefix web install
npm --prefix web run build      # the server's page and the virtual WLED's screen
uv run treemap --help
```

Rebuild the pages after pulling changes to `web/`. The scan page needs building only to
work on it (`npm --prefix scanapp install`): the phone uses the hosted copy.

Every command below is run as `uv run treemap …` from the project folder.

## Running each part

| Part | What it is | Run it | Open |
|---|---|---|---|
| **The server** | The server and its page: devices, their LEDs in 3D, effects, favourites, playlists, the QR codes for the scan page. Drives the WLED controllers over DDP. | `treemap serve` | `http://<this computer>:8765/` |
| **The scan page** | The phone's side of a scan: wiring check, exposure and colours, rounds, review. Hosted on Cloudflare Pages. | nothing: open a device's QR code on the server's page | <https://treemap-scan.pages.dev/> in Chrome on Android |
| **A virtual WLED** | This computer acting as a WLED controller with a simulated tree or flat layout on screen, to scan with the phone without real LEDs. | `treemap sim wled` | opens by itself; add the `<ip>:8780` it prints on the server's page |

- **Server and virtual WLED together** (scan a screen with the phone): run `treemap sim
  wled` and `treemap serve` in two terminals, then add the virtual WLED's address on the
  server's page. See [A virtual WLED](#a-virtual-wled-scan-your-screen).
- To work on the pages with hot reload (`npm --prefix web run dev`,
  `npm --prefix scanapp run dev`), see [Development](#development).

## The server: `treemap serve`

`treemap serve` drives your WLED controllers, runs their scans and plays effects on
them. It needs nothing in the config and keeps running while controllers are off. It
listens on every interface on port 8765 (`server.port`) and prints its address; open it
in a browser:

```sh
treemap serve                 # then open http://<this computer>:8765/
```

**The server's page** lists the **devices**: one per WLED controller, each with its own
LEDs, map, scans and effects. The first time there are none.

- **Add a controller** by its address (`192.168.1.50`, `wled-tree.local`, or with a
  port for the virtual WLED). Its LED count and name are read from WLED. One that's off
  can be added too; the server picks it up when it answers. The list is kept in
  `data/devices.json`, each device's map and scans in `data/devices/<id>/`.
- **Open a device** to see whether it answers, its **QR code** for the scan page on the
  phone, and its LEDs **in 3D** where the scan placed them, lit as they are now. Drag
  to turn, scroll to zoom.
- **Effects** play on the device: pick one and tune it, keep it as a favourite (☆), make
  **playlists** of favourites with times and crossfades. Favourites and playlists are
  shared by all devices (`data/library.json`). Switch **Send to the LEDs** off to
  preview an effect on the page only; a device that's off shows effects there too.
- **Timing** (under Now playing, while an effect plays): the frames per second sent,
  the gap between frames, and the time to render and send each one, over the last 2 s.
  If it reads steady while the LEDs still speed up and slow down, the frames are held
  up on the Wi-Fi or in the controller, not by the server: on a Mac, AirDrop's
  background radio (`sudo ifconfig awdl0 down` to test) or WLED's WiFi sleep ("Disable
  WiFi sleep" in WLED's WiFi Settings) are the usual causes.
- **Front** (tree) or **Bottom** (flat), once a device has a map: **Set it** shows it on
  the LEDs (stopping the effect) and in the 3D view, as on the scan page's Review screen:
  a white stripe at the front, or the bottom edge white and the left side red. Turn it
  with the slider or the buttons, by the degree (and in quarter turns for a flat
  layout, with **Mirror**), then **Save**. Every effect follows it.
- A map from the earlier command-line version (`data/tree_map.json`) can be taken over by
  a device with the same LED count, from its page.
- One device is one controller: a tree split over two controllers isn't covered yet.

WLED shows the server's colours while they keep arriving and goes back to its own effect
a few seconds after they stop. If WLED's settings show "Receive UDP realtime" switched
off (Sync Interfaces), switch it on. Keep WLED's own brightness at full: it dims the
server's colours too (the server has its own, `engine.brightness`).

The API is under `/api/v2` (see [treemap/api/app.py](treemap/api/app.py) and
[treemap/api/device.py](treemap/api/device.py)). The server's own endpoints are
`/info`, `/devices`, `/effects`, `/favourites` and `/playlists`; each device's are under
`/devices/<id>`: `/leds` (test patterns), `/play`, `/brightness`, `/stop`, `/frame`,
`/send`, `/scan/*` and `/map`. For example, `curl -X POST -H 'Content-Type:
application/json' -d '{"mode":"chase"}' http://<server>:8765/api/v2/devices/<id>/leds`
runs the chase. Other web pages may only use the API if they're in `server.origins`
(the scan page is, and so is `server.scan_page`).

## The scan page

The phone's side is a web page, **<https://treemap-scan.pages.dev/>** (source in
[scanapp/](scanapp/)). It only scans. Open it from a device's **QR code** on the server's
page, which fills in the server and the device (`?server=http://<ip>:8765&device=<id>`),
in **Chrome on an Android phone** on the same Wi-Fi, and allow it to reach devices on
your local network when Chrome asks. Then:

1. **Connect:** the page shows the server, the device and its map. Pick **tree** or
   **flat**. Opened without a device, it lists the server's devices to pick from.
2. **Check the wiring:** a light runs from the first LED to the last; if it doesn't run
   in order, fix the LED settings in WLED. You can also light one LED by number.
3. **Scan:** the page films with the rear camera (it picks the main lens, the one with
   continuous focus) and uploads the frames while the server runs the rounds. The page
   shows each round's progress and result. After each round the LEDs show it (green,
   yellow, red) until you tap **Start round N** where it's red, or **Finish here**;
   **Stop** keeps the rounds already finished.
4. **Review:** fix missing LEDs and set which way the map faces (below).

Each scan first sets the phone up:

- **Exposure.** The LEDs show the code's colours along the strip while the page tries
  exposures, darkest first: 0.5 to 8 ms at ISO 100, then ISO 200 to 1600 at 8 ms, and
  the server counts the LEDs seen in each. It keeps the darkest that sees at least 95%
  as many as the best. An exposure that sees more spots than there are LEDs, or lights
  over 15% of the picture, is too bright and never picked. A strip of the exposures
  tried, each with a bar of the LEDs it saw, lets you tap another; **Continue** goes
  on. The start screen can reuse the exposure last used with this camera (the phone
  remembers it) instead of searching.
  Phones without manual exposure let automatic exposure settle, then lock it. The white
  balance is locked too.
- **Colours.** The LEDs show red, green, blue and white in turn and the server measures
  how this phone sees each colour. It keeps the result per phone (model and camera) in
  `data/camera_colours/`, and the page shows the share of each colour read right (85%
  passes).

**Review** (after a scan, or from the connect screen):

- **Fix LEDs:** red and yellow runs are listed; tap one to light it blue on the LEDs, then
  **scan this part again** (more rounds, added to the scan's) and film it. A misplaced
  LED can have its readings ignored, so it's placed between its neighbours; a rising
  plane helps find one.
- **Front (tree):** a vertical stripe lights at the map's front; drag the slider until it
  faces the room. **Bottom (flat):** the bottom edge lights white and the left side red;
  turn it by any angle (the slider, or quarter turns), and mirror it if the strips were
  filmed from behind. The map keeps its positions and stores the turn alongside them, so
  every effect follows it and it can be changed later without scanning again. The
  server's page can set both too (see [The server](#the-server-treemap-serve)).

### Scanning well

- A dark room. If colours are misread, lower `scan.brightness` or raise
  `scan.symbol_ms`.
- **A tree: walk round it**, keeping it roughly in frame. Turning on the spot gives the
  solve nothing to work with. Hold the phone roughly level: the solve takes "up" from
  the horizon.
- **A flat layout:** put the phone where it sees all of the LEDs, on something steady,
  looking down at them (straight down or at an angle both work). It may also move round;
  it doesn't have to. All the LEDs lie in one plane, so the flat scan maps every photo
  onto one reference photo instead of solving 3D positions, then works out the angle the
  phone looked from: the tilt that makes neighbouring LEDs as evenly spaced as they are
  on the strip. The map comes out as seen square-on, with "up" the top of the phone's
  picture until you set the bottom.
- The LEDs must not move during the scan.
- Check the wiring first, so the LED order is right.

### What the statuses mean

| Status | Meaning |
|---|---|
| **ok** | Seen from at least 3 camera positions spread over 15° or more; placed to within about a centimetre on a simulated tree. |
| **interpolated** | Not measured well (hidden, misread, or a short gap). Placed between its neighbours on the strip. Usually within a few cm. |
| **failed** | A longer gap, a strip end or the join between two strips. The position is only a rough guess. |

## A virtual WLED: scan your screen

`treemap sim wled` turns this computer into a WLED controller with a simulated tree (or
flat layout) on its screen, so the whole flow can be tried with only a phone: the scan
page, the server, DDP, the "LEDs" and the camera. The tree grows like a fir (whorls of
drooping branches covered in needles, the lights clipped onto them), and its LEDs light
up the branches round them.

```sh
treemap sim wled              # opens the page; --new flat (or tree) starts a new layout
```

It prints its address (`<ip>:8780`): add that on the server's page, and `treemap serve`
drives it like real LEDs, marked as virtual. The server reads the LED count from its
`/json/info` and sends colours over DDP to UDP 4048. Then scan from the phone as usual,
from the device's QR code, filming the screen:

- **Turn it on screen (rotate, the default):** drag to turn round it, scroll to zoom.
  **Turn by itself** (or `Space`) turns a tree slowly, once round in 10–120 s, so a
  phone held still in front of the screen films it as if walking round it.
- **Or walk round it (walk):** `M` switches modes. Click the view, then `WASD` or the
  arrows to move, the mouse to look, `Space` up and `Shift` down; `Esc` lets go of the
  mouse.
- `R` goes back to the start, `H` hides the panel (it also hides while you walk), and
  `L` switches the **test lights** (white, or the code's colours along the strip), which
  light the layout from the page while `treemap serve` shows nothing (sends nothing, or
  only its dark still frame).
- **Hold the phone square-on to the screen, with the layout in the middle.** The scan
  assumes one camera; filming a screen at an angle skews the picture in a way it doesn't
  model.
- **New layouts:** the panel makes a new tree, or a flat layout in rows or a spiral, with
  any LED count and number of strips. After changing the LED count, open the device on
  the server's page and use the new count (its map must then be scanned again).

The layout is kept in `data/virtual_wled.json`. A controller's address may carry a port
like this for WLED's JSON API; DDP always goes to port 4048. macOS may ask whether
Python may accept incoming connections: allow it, or DDP from another machine won't
arrive.

## Configuration

`config.yaml` in the project folder lists every key with its default and what it does.
Put your own settings in `config.local.yaml` next to it: git ignores that file, and
treemap reads it instead of `config.yaml` when it exists. Every key is optional, so it
only needs what differs from the defaults. Use `-c other.yaml` or `TREEMAP_CONFIG` to
choose another file. There are no controllers in the config: add them on the server's
page. The keys you're most likely to change:

| Key | What it does |
|---|---|
| `shape` | The shape a device's map has until a scan says otherwise: `tree` (mapped in 3D) or `flat` (mapped in 2D). |
| `scan.round_s`, `scan.status_s` | Seconds of flashing per round, and of the result when the scan doesn't wait for the phone. |
| `scan.countdown_s` | Seconds the LEDs glow dim white before a scan, to point the camera at them. |
| `scan.max_rounds` | Stop after this many rounds (the scan also stops once every LED is ok). |
| `scan.symbol_ms` | How long each colour of the code shows. Slow it down if the camera misreads colours. |
| `scan.brightness` | LED brightness while flashing, 0–255. Lower stops the camera clipping colours to white. |
| `scan.fov_deg` | The phone camera's horizontal field of view; a starting guess the solve refines. |
| `engine.fps`, `engine.brightness`, `engine.crossfade` | Effects frame rate, overall brightness 0–1, and the blend time when switching effects. |
| `engine.gamma` | Gamma correction of effect frames; `null` = 2.2 (LEDs are linear). The virtual WLED, a screen, always gets 1. |
| `server.host`, `server.port` | Where `treemap serve` listens: every interface (`0.0.0.0`, so the phone reaches it) on 8765. |
| `server.origins` | The web pages allowed to use the server's API from a browser (the scan page, and `localhost:5173` for development). |
| `server.scan_page` | The scan page the device QR codes open; it's allowed too. |

The earlier command-line version's keys (`output`, `controllers`, `camera`, `sim`,
`scan.camera_fps`) are ignored, with a warning when the server starts: delete them.

## Files

| Path | Contents |
|---|---|
| `data/devices.json` | The server's devices: name, address, LED count. |
| `data/devices/<id>/tree_map.json` | A device's map: a position and status per LED. Heights run 0 (lowest LED) to 1 (highest); x and z are centred on the trunk at the same scale. It can also hold an `orientation` (the front, or a flat map's turn and mirror), set on the scan page's Review screen or the server's page. Only the current map: a new scan replaces it. |
| `data/devices/<id>/scans/<profile>/` | The device's last scan's rounds (which LED was at which pixel in each photo), and the LEDs whose readings are ignored (`overrides.json`). |
| `data/library.json` | Favourites and playlists, shared by every device. |
| `data/camera_colours/<phone>.json` | How each phone (model and camera) sees the code's colours, and its exposure search's counts, from the scan page. |
| `data/virtual_wled.json` | The virtual WLED's layout. |

## Troubleshooting

- **Effects speed up and slow down on the real LEDs**: see **Timing** under
  [The server](#the-server-treemap-serve).
- **A round finds few LEDs**: the phone has to see the LEDs. Step back until they're all
  in the picture, and (for a tree) keep moving round it.
- **"no camera frames arrived"**: the scan page has to stay open and filming during the
  scan.
- **Solve again refused with "filmed at different sizes" or "LEDs beyond the tree's N"**:
  the saved rounds don't fit. Scan again.
- **WLED now has a different number of LEDs**: the device page offers to use the new
  count; the map must then be scanned again.
- **The page still shows the old version after an update**: rebuild it
  (`npm --prefix web run build`) and reload the page.
- **"The pages aren't built yet"**: run `npm --prefix web install` and
  `npm --prefix web run build`.

## Development

```sh
uv run pytest
npm --prefix web run dev      # the pages with hot reload; keep `treemap serve` running
```

`npm --prefix web run dev` serves the pages at <http://localhost:5173/>: open
`/server.html`. Its `/api/v2` calls go to `treemap serve` on `TREEMAP_SERVE_PORT` (default
8765). `npm --prefix web run build` builds both pages into `treemap/web_dist/`:
`server.html` (`treemap serve` serves it) and `wled.html` (`treemap sim wled`'s screen).

The scan page (`scanapp/`, Vite + Svelte 5 + TypeScript) talks to `treemap serve` across
origins, as it does from Cloudflare Pages. With the virtual WLED to scan:

```sh
treemap sim wled                    # add its address on the server's page
treemap serve
npm --prefix scanapp run dev        # http://localhost:5173/?server=http://127.0.0.1:8765
```

`localhost` counts as a secure page, so the camera works there too (on a laptop, its
webcam). `npm --prefix scanapp run build` writes `scanapp/dist/`, which is what Cloudflare
Pages serves. It's deployed by hand for now:

```sh
npm --prefix scanapp run build && wrangler pages deploy scanapp/dist --project-name treemap-scan --branch main
```

The Python code is in `treemap/`. The pages (Vite + Svelte 5 + TypeScript + three.js) are
in `web/src/`: `server/` the server's page, `wled/` the virtual WLED's screen, `3d/` the
fir tree they draw, and `components/ui/` the small building blocks they share.

| Module | Contents |
|---|---|
| `api/` | `treemap serve`'s HTTP API (`/api/v2`): the server's endpoints and each device's. |
| `devices.py` | The devices `treemap serve` drives, kept in `data/devices.json`. |
| `cameras/` | The camera interface, the phone's uploaded frames, and the colour check. |
| `outputs/` | The LED output interface and the WLED (DDP) output. |
| `scan/` | The LED code, blob tracking and decoding, measured camera colours, structure from motion (tree), the flat solve, scan rounds, cleanup, and evaluation against a simulated tree (for the tests). |
| `mapping/` | The map file and its status colours. |
| `effects/` | The effects. |
| `engine.py` | Runs effects at a fixed frame rate, and times it. |
| `library.py`, `player.py` | Favourites and playlists, and what the engine plays (an effect, a favourite or a playlist). |
| `workflow.py`, `jobs.py` | The scan, solve-again and ignore-an-LED steps, run in the background for a device. |
| `sim/` | The tree and flat layout generators, and the virtual WLED. |
| `pages.py` | Where the built pages are. |

[PLAN-2.0.md](PLAN-2.0.md) has the plan and what's next.
