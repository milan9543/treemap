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

> **Status:** the simulator, scanning, mapping checks, the effects engine, the WLED
> output (`output: wled`) and the Android camera (`camera: android`) work. Scanning the
> real LEDs hasn't been tried end to end yet; see [ROADMAP.md](ROADMAP.md).

## Install

You need [uv](https://docs.astral.sh/uv/), Python 3.11 or newer, and Node.js 20.19+ or
22.12+ to build the viewer.

```sh
uv sync
npm --prefix viewer install
npm --prefix viewer run build
uv run treemap --help
```

Rebuild the viewer after pulling changes to `viewer/`.

Every command below is run as `uv run treemap …` from the project folder.

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
2. **Scan**: press **Start scanning**. The view switches to walk mode and the LEDs start
   flashing their codes. Walk round the tree:
   - `W` `A` `S` `D` move, the mouse looks round, `Space` and `Shift` go up and down;
   - the panel at the top shows the round, its time left and how many LEDs were
     identified; the **phone** in the bottom right shows what the virtual phone films,
     with identified LEDs circled green;
   - every round ends with status colours on the tree: green placed, yellow
     interpolated, red unknown. Walk towards the red parts;
   - `Esc` pauses: from there **Resume walking**, **Stop scan** or **Leave walk mode**.
     The scan also stops by itself once every LED is ok, or after `scan.max_rounds`.

   Each round writes `data/tree_map.json`. **Solve again** re-solves from the saved
   rounds; **Start over** forgets them.
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
   "front" is wherever the scan started, so effects that turn round the trunk can start
   at a different angle on each.

   Press ☆ in Now playing to keep the running effect, with its settings, under
   **Favourites**: click one to play it, ✎ to rename it, 🗑 to delete it. If you change
   a favourite's settings while it plays, **Update it** saves the new ones. Favourites
   are kept in this browser (localStorage), so they don't follow you to another browser.

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
| Start a scan over | `treemap scan --fresh` |
| Solve again from the saved rounds | `treemap reconstruct` |
| Show the mapping quality | `treemap show-mapping` (add `--verify` for the sweep) |
| Inspect and fix one LED | `treemap fix 57` (asks: interpolate, measure again or keep) |
| Accuracy against the simulator | `treemap sim evaluate` |
| List effects | `treemap effects` |
| Run an effect | `treemap run rainbow -p speed=0.5 --seconds 30` |
| Run a 3D effect on the true positions | `treemap run plane -p direction=around --map truth` |
| Check the WLED controllers' settings | `treemap wled check` |
| Check the camera can scan (and measure its colours) | `treemap camera check [--brightness 100]` |
| Show the config | `treemap config show` |

`treemap scan` needs the viewer open, because the viewer's virtual phone films the
tree. Rounds that finished are kept, so a stopped scan continues where it left off.

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

`config.yaml` in the project folder. Every key is optional, and `treemap config show`
prints the effective values. Use `-c other.yaml` or `TREEMAP_CONFIG` to choose another
file. The number of LEDs isn't a key: in the simulator it's the simulated tree's, on the
real tree it's where the last controller's LEDs end. The keys you're most likely to
change:

| Key | What it does |
|---|---|
| `output` | `sim` (the browser viewer) or `wled` (the controllers, see [Real LEDs](#real-leds-wled)). |
| `controllers` | WLED controllers, each owning a slice of the LED indices; `reverse: true` for a strip wired from the other end. |
| `camera.type`, `camera.url` | `sim` (the viewer's virtual phone), or `android` with the IP Webcam URL (see [Real camera](#real-camera-an-android-phone)). |
| `camera.fov_deg` | The phone camera's horizontal field of view; a starting guess the solve refines. |
| `scan.round_s`, `scan.status_s` | Seconds of flashing per round, and of status colours between rounds. |
| `scan.max_rounds` | Stop after this many rounds (the scan also stops once every LED is ok). |
| `scan.symbol_ms` | How long each colour of the code shows. Slow it down if a real camera misreads colours. |
| `scan.brightness` | LED brightness while flashing, 0–255. Lower stops a real camera clipping colours to white. |
| `scan.camera_fps` | Photos per second the virtual phone sends. |
| `scan.profile` | Scan rounds are kept in `data/scans/<profile>/`. |
| `engine.fps`, `engine.brightness`, `engine.crossfade` | Effects frame rate, overall brightness 0–1, and the blend time when switching effects. |
| `engine.gamma` | Gamma correction of effect frames. `null` = 1 in the simulator (the screen already applies one) and 2.2 on WLED (LEDs are linear). |
| `sim.strips`, `sim.height`, `sim.radius`, `sim.layout`, `sim.seed` | Defaults for generated trees (`null` = random). |
| `sim.hidden_leds` | LEDs the virtual phone never sees, e.g. `"57, 120-127"`, to try out fixing bad LEDs. |

## Files

| Path | Contents |
|---|---|
| `data/sim_tree.json` | The simulated tree: true LED positions, how it was wired, and its branches. |
| `data/scans/<profile>/round_XX.npz` | One scan round: which LED was at which pixel in each photo. |
| `data/scans/<profile>/overrides.json` | LEDs you asked to interpolate. |
| `data/camera_colours.json` | How the camera sees each colour of the code, from `treemap camera check`. |
| `data/camera_check/*.jpg` | One frame of each colour from the last `treemap camera check`. |
| `data/tree_map.json` | The result: a position and status per LED. Heights run 0 (lowest LED) to 1 (highest); x and z are centred on the trunk at the same scale. |

## Real LEDs: WLED

treemap streams colours to WLED controllers over DDP (UDP port 4048), the realtime
protocol WLED receives by default. In `config.yaml`:

```yaml
output: wled
controllers:
  - {host: 192.168.1.51, start: 0, count: 400, reverse: false}
```

- `host` is the controller's IP address or name (`wled-xxxx.local`). If the name doesn't
  resolve, use the IP address shown in the WLED app.
- Each controller drives the LEDs `start` to `start + count - 1` of treemap's numbering,
  as its own LEDs 0, 1, …; `reverse: true` if its strip is wired from the other end.
  Between them, the controllers cover every LED from 0. That's also how many LEDs
  treemap drives.

Then:

1. `treemap wled check` asks each controller for its settings. It warns if WLED is set
   up for a different number of LEDs than `count`, or if WLED's own brightness is below
   full (it dims treemap's colours as well; treemap has `engine.brightness`).
2. `treemap test chase` runs a light from LED 0 to the last one: check the order and
   that each strip starts where you expect. `treemap test led 57` lights one LED.
3. `treemap run rainbow` (or any effect) runs it on the LEDs. The 3D effects need a
   scanned map. `treemap sim view` drives the controllers from the viewer's Effects step
   too; its 3D view still shows the simulated tree, not your LEDs.

WLED shows treemap's colours while they keep arriving and goes back to its own effect a
few seconds after they stop. If WLED's settings show "Receive UDP realtime" switched
off (Sync Interfaces), switch it on. `engine.gamma` defaults to 2.2 on WLED.

## Real camera: an Android phone

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

A scan locks the exposure and white balance itself if they aren't already.

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
  different number of LEDs (in the simulator, before you generated a new one). Scan again
  with **Start over** (`--fresh`).
- **"the viewer's camera isn't reachable"** or **"no camera frames arrived"**: the scan
  films through the viewer, so keep `treemap sim view` running and the viewer page open.
- **A round finds few LEDs**: the phone has to see the tree. Walk back until the whole
  tree is in the phone inset, and keep moving round it.
- **Scan refused with "filmed at different sizes" or "LEDs beyond the tree's N"**: the
  earlier rounds don't fit. Scan again with **Start over** (`--fresh`).
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
| `scan/` | The LED code, blob tracking and decoding, structure from motion, scan rounds, cleanup and evaluation. |
| `mapping/` | The tree map file and the quality views. |
| `effects/` | The effects. |
| `engine.py` | Runs effects at a fixed frame rate. |
| `workflow.py` | The scan, reconstruct and fix steps, shared by the CLI and the viewer. |
| `jobs.py` | Runs those steps in the background for the viewer. |
| `sim/` | The tree generator and the server. |

[ROADMAP.md](ROADMAP.md) has the plan and what's next.
