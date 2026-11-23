# treemap

Map where each LED of a WLED Christmas tree really is, using a phone camera, then run
effects that use those 3D positions: a plane sweeping up the tree, a rainbow turning
round it, and so on.

Scanning works like this: every LED flashes its own colour code at once while you walk
round the tree filming it. After each round of about 12 seconds, the tree lights up green
where LEDs are placed, yellow where they were filled in from their neighbours, and red
where they're still unknown. Walk to the red parts and the next round fills them in.

Everything also runs in a **simulator**: a random virtual tree in a browser 3D viewer,
which you walk round in first person while a virtual phone films it. You can try the
whole workflow (scan, check, fix, run effects) before the hardware arrives. The virtual
tree grows like a fir (whorls of drooping branches covered in needles, the lights clipped
onto them), and its LEDs light up the branches and the floor round them, in the 3D view
and, more faintly, in the phone's photos.

treemap 2.0 ([PLAN-2.0.md](PLAN-2.0.md)) moves this onto a **server** and the **phone**: you
add your WLED controllers on the server's web page, scan each one from a page on the
phone, and play effects from the server's page. No IP Webcam app, no config file.

> **Status:** 1.x works: the simulator, scanning, mapping checks, the effects engine,
> the WLED output and the Android camera (IP Webcam). A flat layout has been scanned on
> real LEDs; a real tree not yet. From 2.0, phases 1–6b are built: the server with
> several devices and its page, the scan page (wiring, exposure and colours, rounds,
> review with front and bottom), effects, favourites and playlists, and a virtual WLED.
> They're tested on this Mac, not yet with the phone or the real tree. Still to come:
> Home Assistant (MQTT), Docker and the add-on, the offline scan page. See
> [PLAN-2.0.md](PLAN-2.0.md).

## Install

You need [uv](https://docs.astral.sh/uv/), Python 3.11 or newer, and Node.js 20.19+ or
22.12+ to build the web pages.

```sh
uv sync
npm --prefix viewer install
npm --prefix viewer run build      # the viewer and the server's page
uv run treemap --help
```

Rebuild the viewer after pulling changes to `viewer/`. The scan page needs building only
to work on it (`npm --prefix scanapp install`): the phone uses the hosted copy.

Every command below is run as `uv run treemap …` from the project folder.

## Running each part

| Part | What it is | Run it | Open |
|---|---|---|---|
| **The server** | 2.0's server and its page: devices, their LEDs in 3D, effects, favourites, playlists, the QR codes for the scan page. Drives the WLED controllers over DDP. | `treemap serve` | `http://<this computer>:8765/` |
| **The scan page** | The phone's side of a scan: wiring check, exposure and colours, rounds, review. Hosted on Cloudflare Pages. | nothing: open a device's QR code on the server's page | <https://treemap-scan.pages.dev/> in Chrome on Android |
| **A virtual WLED** | This computer acting as a WLED controller with a simulated tree or flat layout on screen, to scan with the phone without real LEDs. | `treemap sim wled` | opens by itself; add the `<ip>:8780` it prints on the server's page |
| **The simulator viewer** | 1.x: a virtual tree in 3D, walked round with a virtual phone; scan, map and effects all on screen. | `treemap sim view` | <http://127.0.0.1:8765/> (opens by itself) |
| **The command line** | 1.x: scan, fix and run effects on the tree in `config.yaml` (the simulator's, or `output: wled`). | `treemap scan`, `treemap run rainbow`, … ([table](#the-same-from-the-command-line)) | — |

- **Server and virtual WLED together** (scan a screen with the phone): run `treemap sim
  wled` and `treemap serve` in two terminals, then add the virtual WLED's address on the
  server's page. See [A virtual WLED](#a-virtual-wled-scan-your-screen).
- `treemap serve` and `treemap sim view` both default to port 8765: to run both, give
  one another port (`treemap serve --port 8766`).
- To work on the pages with hot reload (`npm --prefix viewer run dev`,
  `npm --prefix scanapp run dev`), see [Development](#development).

## Quick start: the web viewer

```sh
uv run treemap sim view
```

This opens the viewer at <http://127.0.0.1:8765/>. If there's no simulated tree yet, it
generates one. Leave it running: the viewer can do everything the command line can.

The top bar walks through the workflow: **Tree → Scan → Map → Effects** (keys `1`–`4`).
The sidebar shows the current step and the 3D view fills the rest. On the right of the
top bar, the **LEDs** pill shows what's lighting the LEDs (an effect, the scan, or
nothing) with a Stop button, and ⚙ opens the configuration and the keyboard shortcuts.

1. **Tree** (simulator only): set up the strips, size and layout, then press
   **Generate**. Leave a field blank to randomise it.
2. **Scan**: press **Start scanning**. A scan starts over: the earlier one's rounds are
   forgotten. First the LEDs glow dim white for `scan.countdown_s` (5 s) while you get
   the camera pointed at them; with a real phone its exposure and colours are set next
   (see [Real camera](#real-camera-an-android-phone)). Then the view switches to walk
   mode and the LEDs start flashing their codes. Walk round the tree:
   - `W` `A` `S` `D` move, the mouse looks round, `Space` and `Shift` go up and down;
   - the panel at the top shows the round, its time left and how many LEDs were
     identified; the **phone** in the bottom right shows what the virtual phone films,
     with identified LEDs circled green;
   - every round ends with status colours on the tree: green placed, yellow
     interpolated, red unknown. Walk towards the red parts;
   - `Esc` pauses: from there **Resume walking**, **Stop scan** or **Leave walk mode**.
     The scan also stops by itself once every LED is ok, or after `scan.max_rounds`.

   Each round writes `data/tree_map.json`, solved from all the rounds of this scan.
   **Solve again** re-solves from them.
3. **Map**: how many LEDs are placed, interpolated or failed.
   - **Status colours** and **Verify sweep** check the map on the tree. In the sweep, an
     LED that lights out of step with its neighbours is in the wrong place.
   - In the simulator, **Accuracy vs the true tree** gives the error per status.
     **Show** switches the 3D view to Compare.
   - Click a problem LED (or any LED in the 3D view) to light it blue and inspect it.
     **Interpolate** fills it in from its neighbours; to measure it better, scan again
     and film that part of the tree.
4. **Effects**: click an effect to run it. Its controls and the master brightness are
   under **Now playing**. The **3D** effects (plane, 3D colour bands, spiral, bursts, ripples,
   plasma, radar, fireflies, fill up, fill outwards, campfire, 3D checkerboard) colour each LED by where it is on
   the tree, always in Christmas colours (red, green, gold and white). Those that don't
   light every LED have a **background** colour, at its own brightness, for the LEDs the
   animation isn't lighting. The switch on that card picks their positions:
   the **Scanned map** (what the real tree will use) or, in the simulator, the **True
   tree**. Compare the two to see how much the scan's errors show. The scanned map's
   "front" is wherever the scan started (the scan page's Review screen can turn it, see
   [The scan page](#the-scan-page)), so effects that turn round the trunk can start at a
   different angle on each.

   Press ☆ in Now playing to keep the running effect, with its settings, under
   **Favourites**: click one to play it, ✎ to rename it, 🗑 to delete it. If you change
   a favourite's settings while it plays, **Update it** saves the new ones. Favourites
   are kept by the server in `data/library.json`, shared with `treemap serve`'s page
   (which also makes playlists of them). Favourites an older viewer kept in
   the browser move there the first time it connects.

The toolbar at the bottom of the 3D view switches between **Truth**, **Scanned** and
**Compare** (`t` cycles). Compare draws a line from each LED's true position to where the
scan put it, coloured green (spot on) to red (5 cm or more off); hover an LED to see its
error. In the simulator the scanned map is shown aligned onto the truth (best rotation,
scale and offset). **Layers** shows or hides the unlit LEDs (`o`), the cone (`c`), the
branches and floor, lit by the LEDs (`b`), and the wire path (`w`). LEDs deep in the
branches still show as a faint glow through the needles. Drag to orbit,
scroll to zoom, `r` resets the view, `f` toggles walk mode and `[` the sidebar.

## The same from the command line

Keep `treemap sim view` running in one terminal to watch; run these in another.

| Step | Command |
|---|---|
| Make a new random tree | `treemap sim new [--seed 42] [--strip 200:14:top …]` |
| Check the wiring order | `treemap test chase`, `treemap test led 57`, `treemap test off` |
| Scan (walk round the tree in the viewer meanwhile) | `treemap scan [--rounds 3]` |
| Solve again from the saved rounds | `treemap reconstruct` |
| Show the mapping quality | `treemap show-mapping` (add `--verify` for the sweep) |
| Inspect and fix one LED | `treemap fix 57` (asks: interpolate, measure again or keep) |
| Accuracy against the simulator | `treemap sim evaluate` |
| List effects | `treemap effects` |
| Run an effect | `treemap run rainbow -p speed=0.5 --seconds 30` |
| Run a 3D effect on the true positions | `treemap run plane -p direction=around --map truth` |
| Check the WLED controllers' settings | `treemap wled check` |
| Run the 2.0 server and its page | `treemap serve` (see [The server](#the-server-treemap-serve)) |
| Act as a WLED controller on this screen | `treemap sim wled [--new flat]` (see [A virtual WLED](#a-virtual-wled-scan-your-screen)) |
| Check the camera can scan (and measure its colours) | `treemap camera check [--brightness 100]` |
| Show the config | `treemap config show` |

In the simulator, `treemap scan` needs the viewer open, because the viewer's virtual
phone films the tree. Every scan starts over; a stopped scan keeps the rounds it
finished (for `treemap reconstruct` and `treemap fix`) until the next scan.

## What the statuses mean

| Status | Meaning |
|---|---|
| **ok** | Seen from at least 3 camera positions spread over 15° or more; placed to within about a centimetre in the simulator. |
| **interpolated** | Not measured well (hidden, misread, or a short gap). Placed between its neighbours on the strip. Usually within a few cm. |
| **failed** | A longer gap, a strip end or the join between two strips. The position is only a rough guess. |

To deal with a yellow or red LED, select it in the Mapping panel or run `treemap fix N`:

- **Scan again** and film that part of the tree from a few directions. New rounds add to
  the old ones.
- **Interpolate** ignores its observations from now on, for example an LED the camera
  keeps misreading. It's stored in `data/scans/<profile>/overrides.json`;
  **Measure again** undoes it.

## Configuration

`config.yaml` in the project folder lists every key with its default and what it does.
Put your own settings in `config.local.yaml` next to it: git ignores that file, and
treemap reads it instead of `config.yaml` when it exists. Every key is optional, so it
only needs what differs from the defaults. `treemap config show` prints the effective
values and which file they came from. Use `-c other.yaml` or `TREEMAP_CONFIG` to choose
another file. The number of LEDs isn't a key: in the simulator it's the simulated tree's, on the
real tree it's where the last controller's LEDs end. The keys you're most likely to
change:

| Key | What it does |
|---|---|
| `shape` | `tree` (mapped in 3D) or `flat` (strips on the floor or a wall, mapped in 2D; see [Flat layouts](#flat-layouts-strips-on-the-floor-or-a-wall)). |
| `output` | `sim` (the browser viewer) or `wled` (the controllers, see [Real LEDs](#real-leds-wled)). |
| `controllers` | WLED controllers in LED order; only `host` is needed (the LED count is read from WLED). `reverse: true` for a strip wired from the other end. |
| `camera.type`, `camera.url` | `sim` (the viewer's virtual phone), or `android` with the IP Webcam URL (see [Real camera](#real-camera-an-android-phone)). |
| `camera.fov_deg` | The phone camera's horizontal field of view; a starting guess the solve refines. |
| `scan.round_s`, `scan.status_s` | Seconds of flashing per round, and of status colours between rounds. |
| `scan.countdown_s` | Seconds the LEDs glow dim white before a scan, to point the camera at them. |
| `scan.max_rounds` | Stop after this many rounds (the scan also stops once every LED is ok). |
| `scan.symbol_ms` | How long each colour of the code shows. Slow it down if a real camera misreads colours. |
| `scan.brightness` | LED brightness while flashing, 0–255. Lower stops a real camera clipping colours to white. |
| `scan.camera_fps` | Photos per second the virtual phone sends. |
| `scan.profile` | Scan rounds are kept in `data/scans/<profile>/`. |
| `engine.fps`, `engine.brightness`, `engine.crossfade` | Effects frame rate, overall brightness 0–1, and the blend time when switching effects. |
| `engine.gamma` | Gamma correction of effect frames. `null` = 1 in the simulator (the screen already applies one) and 2.2 on WLED (LEDs are linear). |
| `sim.strips`, `sim.height`, `sim.radius`, `sim.layout`, `sim.seed` | Defaults for generated trees (`null` = random). |
| `sim.hidden_leds` | LEDs the virtual phone never sees, e.g. `"57, 120-127"`, to try out fixing bad LEDs. |
| `server.host`, `server.port` | Where `treemap serve` listens: every interface (`0.0.0.0`, so the phone reaches it) on 8765. |
| `server.origins` | The web pages allowed to use the server's API from a browser (the scan page, and `localhost:5173` for development). |
| `server.scan_page` | The scan page the device QR codes open; it's allowed too. |

`output` and `controllers` are only for the 1.x commands (`treemap scan`, `treemap run`,
…). `treemap serve` ignores them: its devices are added on its page.

## Files

| Path | Contents |
|---|---|
| `data/sim_tree.json` | The simulated tree: true LED positions, how it was wired, and its branches. |
| `data/scans/<profile>/round_XX.npz` | One scan round: which LED was at which pixel in each photo. |
| `data/scans/<profile>/overrides.json` | LEDs you asked to interpolate. |
| `data/camera_colours.json` | How the camera sees each colour of the code, from `treemap camera check`. |
| `data/camera_check/*.jpg` | One frame of each colour from the last `treemap camera check`. |
| `data/tree_map.json` | The result: a position and status per LED. Heights run 0 (lowest LED) to 1 (highest); x and z are centred on the trunk at the same scale. The map can also hold an `orientation` (the front, or a flat map's turn and mirror), set on the scan page's Review screen. |
| `data/devices.json` | `treemap serve`'s devices: name, address, LED count. |
| `data/devices/<id>/` | One device's map (`tree_map.json`) and its last scan's rounds (`scans/`). Only the current map: a new scan replaces it. |
| `data/library.json` | Favourites and playlists, shared by every device and by the viewer. |
| `data/camera_colours/<phone>.json` | How each phone (model and camera) sees the code's colours, and its exposure search's counts, from the scan page. |
| `data/virtual_wled.json` | The virtual WLED's layout. |

## Real LEDs: WLED

treemap streams colours to WLED controllers over DDP (UDP port 4048), the realtime
protocol WLED receives by default. In `config.yaml`:

```yaml
output: wled
controllers:
  - host: 192.168.1.51
  - {host: 192.168.1.52, reverse: true}
```

- `host` is the controller's IP address or name (`wled-xxxx.local`). If the name doesn't
  resolve, use the IP address shown in the WLED app.
- Each controller's LED count is read from WLED (its LED Preferences), and its LEDs
  follow on from the previous controller's: here 192.168.1.51 drives treemap's LEDs 0
  to 199 and 192.168.1.52 the next 200, if each is set up for 200. `reverse: true` if
  its strip is wired from the other end. `count` and `start` set them by hand instead,
  for example when a controller isn't always on. The last controller's last LED is how
  many LEDs treemap drives.

Then:

1. `treemap wled check` asks each controller for its settings. It warns if WLED is set
   up for a different number of LEDs than a `count` you set, if WLED's own brightness is
   below full (it dims treemap's colours as well; treemap has `engine.brightness`), or if
   WiFi sleep is on (it makes effects stutter).
2. `treemap test chase` runs a light from LED 0 to the last one: check the order and
   that each strip starts where you expect. `treemap test led 57` lights one LED.
3. `treemap run rainbow` (or any effect) runs it on the LEDs, and shows the frame rate
   it keeps, with the time to render and to send each frame. The 3D effects need a
   scanned map. `treemap sim view` drives the controllers from the viewer's Effects step
   too. If the viewer is open, it mirrors what the LEDs show, on the scanned map (with
   a real camera it doesn't show the simulated tree).

WLED shows treemap's colours while they keep arriving and goes back to its own effect a
few seconds after they stop. If WLED's settings show "Receive UDP realtime" switched
off (Sync Interfaces), switch it on. `engine.gamma` defaults to 2.2 on WLED.

## The server: `treemap serve`

`treemap serve` is the server of treemap 2.0 (see [PLAN-2.0.md](PLAN-2.0.md)): it drives
your WLED controllers, runs their scans and plays effects on them. It needs nothing in
the config and keeps running while controllers are off. It listens on every interface
on port 8765 (`server.port`) and prints its address; open it in a browser:

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
  background radio (`sudo ifconfig awdl0 down` to test) or WLED's WiFi sleep are the
  usual causes.
- A map from before devices (`data/tree_map.json`) can be taken over by a device with
  the same LED count, from its page.
- One device is one controller: a tree split over two controllers isn't covered yet.

The API is under `/api/v2` (see [treemap/api/app.py](treemap/api/app.py) and
[treemap/api/device.py](treemap/api/device.py)). The server's own endpoints are
`/info`, `/devices`, `/effects`, `/favourites` and `/playlists`; each device's are under
`/devices/<id>`: `/leds` (test patterns), `/play`, `/brightness`, `/stop`, `/frame`,
`/send`, `/scan/*` and `/map`. For example, `curl -X POST -H 'Content-Type:
application/json' -d '{"mode":"chase"}' http://<server>:8765/api/v2/devices/<id>/leds`
runs the chase. Other web pages may only use the API if they're in `server.origins`
(the scan page is, and so is `server.scan_page`).

### The scan page

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
  turn it in quarter turns, and mirror it if the strips were filmed from behind.
  The map keeps its positions and stores the turn alongside them, so every effect
  follows it and it can be changed later without scanning again.

### A virtual WLED: scan your screen

`treemap sim wled` turns this computer into a WLED controller with a simulated tree (or
flat layout) on its screen, so the whole flow can be tried with only a phone: the scan
page, the server, DDP, the "LEDs" and the camera.

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
  light the layout from the page while `treemap serve` shows nothing (sends nothing, or only its dark still frame).
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

## Real camera: an Android phone

This is the 1.x way, for `treemap scan` and the viewer; with `treemap serve` the phone
uses [the scan page](#the-scan-page) instead. It goes once the scan page has scanned the
real tree.

The scan films through the [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam)
app: start its server, and use the address it shows at the bottom of the screen.

```yaml
camera:
  type: android
  url: http://192.168.1.60:8080
```

640x480 at 30 frames/s is plenty (IP Webcam's Video preferences). Then, in a dark room,
with the phone pointed at the LEDs:

```sh
treemap camera check
```

The LEDs turn white while the phone's exposure and white balance adjust, then they're
locked (on phones where IP Webcam uses manual sensor mode: manual sensor on, white
balance "daylight"). Then the LEDs show red, green, blue and white in turn, and the check
reports the frame rate and how many LEDs it saw and read right in each colour.

It also **measures how this phone sees each colour** and saves it in
`data/camera_colours.json`; the scan reads colours by it. A phone films small LEDs with
washed-out colours (a green LED arrives as something like (83, 125, 95)), which fixed
thresholds would read as white, so run the check before scanning, and again after
changing the phone, its video settings or `scan.brightness`. LEDs that face the phone
clip to white in the middle; their colour is read from the glow round them. It prints
"the camera is ready to scan" when every colour reads right at least 85% of the time;
the code's check digit and the votes over several cycles handle the rest.

**Every scan does this itself** before its first round, after the countdown, so the
exposure and colours always fit the light at the time. On phones where IP Webcam uses
manual sensor mode, it tries exposures from 0.5 to 16 ms (ISO 100) with the LEDs white
and keeps the shortest that sees nearly as many LEDs as the best; on older phones it
lets automatic exposure adjust, then locks it. `treemap camera check` is for trying a
setup out without scanning.

## Flat layouts: strips on the floor or a wall

Without a tree yet, lay the strips out flat (on the floor, or taped to a wall) and set

```yaml
shape: flat
```

Put the phone where it sees all of the LEDs, on something steady, looking down at them
(straight down or at an angle both work), and scan with `treemap scan` or the viewer's
Scan step. The phone may also move round; it doesn't have to.

All the LEDs lie in one plane, so the flat scan maps every photo onto one reference
photo (a homography per photo) instead of solving 3D positions, and takes each LED's
position as the median over the photos. It then works out the angle the phone looked
at the floor from: the tilt that makes the spacing between neighbouring LEDs as even as
it is on the strip. The map comes out as seen square-on, with "up" being the top of the
phone's picture and z = 0, so effects that sweep up, across or out from the middle work;
those that turn round a tree's trunk don't mean much. The scan page's Review screen can
turn and mirror it so its bottom is where you want it.

The viewer shows a flat map upright, the way the phone saw it. With `output: wled` it
also mirrors what the LEDs show, so you can watch effects and the scan in the browser.

## Scanning the real tree

The scan works the same way as in the simulator; only the output and camera change
(`output: wled`, `camera: android`). Things that matter for a good result:

- A dark room, and `treemap camera check` passing. If colours are misread, lower
  `scan.brightness` or raise `scan.symbol_ms`.
- **Walk round the tree**, keeping it roughly in frame. Turning on the spot gives the
  solve nothing to work with. Hold the phone roughly level: the solve takes "up" from
  the horizon.
- The tree must not move during the scan.
- Run `treemap test chase` first to check the LED order.

## Troubleshooting

- **The LEDs flicker between two patterns, or the status colours blink over an
  effect.** Two programs are sending colours at once, typically a
  `treemap show-mapping` or `treemap test …` still running in a terminal. The viewer
  names them in a warning; stop all but one (Ctrl-C in its terminal).
- **"sim viewer not reachable"**: start `treemap sim view`. The command still works
  without it; you just can't watch.
- **"the tree map has N LEDs but the tree has M"**: the map was scanned on a tree with a
  different number of LEDs (in the simulator, before you generated a new one). Scan again.
- **"the viewer's camera isn't reachable"** or **"no camera frames arrived"**: the scan
  films through the viewer, so keep `treemap sim view` running and the viewer page open.
- **A round finds few LEDs**: the phone has to see the tree. Walk back until the whole
  tree is in the phone inset, and keep moving round it.
- **Solve again refused with "filmed at different sizes" or "LEDs beyond the tree's N"**:
  the saved rounds don't fit. Scan again.
- **The viewer still shows the old version after an update**: rebuild it
  (`npm --prefix viewer run build`) and reload the page.
- **"The viewer isn't built yet"**: run `npm --prefix viewer install` and
  `npm --prefix viewer run build`.

## Development

```sh
uv run pytest
npm --prefix viewer run dev   # viewer with hot reload; keep `treemap sim view` running
```

`npm run dev` serves the viewer at <http://localhost:5173/> and forwards the API and
websockets to the Python server on port 8765 (or `TREEMAP_PORT`).

The scan page (`scanapp/`, Vite + Svelte 5 + TypeScript) talks to `treemap serve` across
origins, as it does from Cloudflare Pages. With the virtual WLED to scan:

```sh
treemap sim wled                    # add its address on the server's page
treemap serve --port 8766           # 8765 if the viewer isn't running
npm --prefix scanapp run dev        # http://localhost:5173/?server=http://127.0.0.1:8766
```

The server's page is part of the viewer project (`viewer/server.html`,
`viewer/src/server/`); `npm --prefix viewer run build` builds it with the viewer, and
`treemap serve` serves it. In `npm --prefix viewer run dev`, open `/server.html`: its
`/api/v2` calls go to `treemap serve` on `TREEMAP_SERVE_PORT` (default 8765).

`localhost` counts as a secure page, so the camera works there too (on a laptop, its
webcam). `npm --prefix scanapp run build` writes `scanapp/dist/`, which is what Cloudflare
Pages serves. It's deployed by hand for now:

```sh
npm --prefix scanapp run build && wrangler pages deploy scanapp/dist --project-name treemap-scan --branch main
```

The Python code is in `treemap/`; the viewer (Vite + Svelte 5 + TypeScript + three.js) is in
`viewer/src/` and builds into `treemap/sim/viewer_dist/`. In the viewer, `lib/` holds the
shared state (Svelte runes), the server connection and the actions; `3d/` the three.js
scene, camera controls and virtual phone; `components/` the shell (top bar, viewport,
overlays) and `components/ui/` the small building blocks; `steps/` one component per
workflow step.

| Module | Contents |
|---|---|
| `cameras/` | The camera interface, the viewer's virtual phone, the Android phone (IP Webcam) and the camera check. |
| `outputs/` | The LED output interface, the viewer output and the WLED (DDP) output. |
| `scan/` | The LED code, blob tracking and decoding, measured camera colours, structure from motion (tree), the flat solve, scan rounds, cleanup and evaluation. |
| `mapping/` | The tree map file and the quality views. |
| `effects/` | The effects. |
| `engine.py` | Runs effects at a fixed frame rate, and times it. |
| `workflow.py` | The scan, reconstruct and fix steps, shared by the CLI, the viewer and the server. |
| `jobs.py` | Runs those steps in the background for the viewer and the server. |
| `api/` | `treemap serve`'s HTTP API (`/api/v2`): the server's endpoints and each device's. |
| `devices.py` | The devices `treemap serve` drives, kept in `data/devices.json`. |
| `library.py`, `player.py` | Favourites and playlists, and what the engine plays (an effect, a favourite or a playlist). |
| `sim/` | The tree generator, the viewer's server and the virtual WLED. |

[PLAN-2.0.md](PLAN-2.0.md) has the 2.0 plan and what's next; [ROADMAP.md](ROADMAP.md) the
1.x one.
