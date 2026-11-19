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
whole workflow (scan, check, fix, run effects) before the hardware arrives.

> **Status:** the simulator, scanning, mapping checks and the effects engine all work. The WLED output (`output: wled`) and the Android camera
> (`camera: android`) aren't built yet; see [ROADMAP.md](ROADMAP.md).

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

1. **Tree** panel (top right): set up the strips, size and layout, then press
   **Generate**. Leave a field blank to randomise it.
2. **Scan** panel (below it): press **Start**. The view switches to walk mode and the
   LEDs start flashing their codes. Walk round the tree:
   - `W` `A` `S` `D` move, the mouse looks round (click the view to capture the mouse,
     `Esc` frees it), `Space` and `Shift` go up and down;
   - the **phone** inset at the bottom shows what the virtual phone films. LEDs it has
     identified are circled green, with every fifth one numbered;
   - every round ends with status colours on the tree and in the Mapping panel. Keep
     walking towards the red parts. The scan stops by itself once every LED is ok, or
     after `scan.max_rounds`; press `Esc` and then **Stop** to end it sooner.

   Each round writes `data/tree_map.json`. **Reconstruct** solves again from the saved
   rounds. **Start over** forgets them.
3. **Mapping** panel (left):
   - **Status colours** lights each LED green (ok), yellow (interpolated) or red
     (failed).
   - **Verify sweep** runs a plane up the tree and then left to right. An LED that
     lights out of step with its neighbours is in the wrong place.
   - **Evaluate** compares the map with the simulated tree's true positions.
   - Click a problem LED (or any LED in the 3D view) to light it blue. **Interpolate**
     fills it in from its neighbours; to measure it better, scan again and film that
     part of the tree.
4. **Truth / Scanned / Compare** (top left, or `t` to cycle) switches between the
   true positions, the scanned ones, and a comparison: a line from each LED's true
   position to where the scan put it, coloured green (spot on) to red (5 cm or more
   off), with the error per status underneath. Hover an LED to see its error. In the
   simulator the scanned map is shown aligned onto the truth (best rotation, scale and
   offset), as **Evaluate** does.
5. **Effects** panel: click an effect to run it; its controls appear below. **Stop**
   turns the LEDs off.

Other controls: drag to orbit, scroll to zoom, `f` toggles walk mode, `r` resets the
view, `o` shows or hides unlit LEDs, `c` the cone, `b` the branches that hide LEDs from
the phone, and `w` the wire path. **Config** shows the effective settings.

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
file. The keys you're most likely to change:

| Key | What it does |
|---|---|
| `led_count` | Total LEDs (400 = 2 × 200). |
| `output` | `sim` (the browser viewer) or `wled` (not built yet). |
| `controllers` | WLED controllers, each owning a slice of the LED indices; `reverse: true` for a strip wired from the other end. |
| `camera.type`, `camera.url` | `sim` (the viewer's virtual phone), or `android` with the IP Webcam URL (not built yet). |
| `camera.fov_deg` | The phone camera's horizontal field of view; a starting guess the solve refines. |
| `scan.round_s`, `scan.status_s` | Seconds of flashing per round, and of status colours between rounds. |
| `scan.max_rounds` | Stop after this many rounds (the scan also stops once every LED is ok). |
| `scan.symbol_ms` | How long each colour of the code shows. Slow it down if a real camera misreads colours. |
| `scan.brightness` | LED brightness while flashing, 0–255. Lower stops a real camera clipping colours to white. |
| `scan.camera_fps` | Photos per second the virtual phone sends. |
| `scan.profile` | Scan rounds are kept in `data/scans/<profile>/`. |
| `engine.fps`, `engine.brightness`, `engine.crossfade` | Effects frame rate, overall brightness 0–1, and the blend time when switching effects. |
| `sim.strips`, `sim.height`, `sim.radius`, `sim.layout`, `sim.seed` | Defaults for generated trees (`null` = random). |
| `sim.hidden_leds` | LEDs the virtual phone never sees, e.g. `"57, 120-127"`, to try out fixing bad LEDs. |

## Files

| Path | Contents |
|---|---|
| `data/sim_tree.json` | The simulated tree: true LED positions and how it was wired. |
| `data/scans/<profile>/round_XX.npz` | One scan round: which LED was at which pixel in each photo. |
| `data/scans/<profile>/overrides.json` | LEDs you asked to interpolate. |
| `data/tree_map.json` | The result: a position and status per LED. Heights run 0 (lowest LED) to 1 (highest); x and z are centred on the trunk at the same scale. |

## Scanning the real tree (once the hardware is supported)

The scan works the same way; only the output and camera change (`output: wled`,
`camera: android`, with IP Webcam streaming from the phone). Things that matter for a
good result:

- A dark room, and the phone's exposure and white balance locked in IP Webcam, so the
  red, green and blue of the code stay apart. If colours are misread, lower
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
- **"the simulated tree has N LEDs but led_count is M"**: make `led_count` match the
  strips, then generate a new tree.
- **"the viewer's camera isn't reachable"** or **"no camera frames arrived"**: the scan
  films through the viewer, so keep `treemap sim view` running and the viewer page open.
- **A round finds few LEDs**: the phone has to see the tree. Walk back until the whole
  tree is in the phone inset, and keep moving round it.
- **Scan refused with "filmed at different sizes" or "LEDs beyond led_count"**: the
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

The Python code is in `treemap/`; the viewer (Vite + TypeScript + three.js) is in
`viewer/src/` and builds into `treemap/sim/viewer_dist/`.

| Module | Contents |
|---|---|
| `cameras/` | The camera interface and the viewer's virtual phone. |
| `outputs/` | The LED output interface and the viewer output. |
| `scan/` | The LED code, blob tracking and decoding, structure from motion, scan rounds, cleanup and evaluation. |
| `mapping/` | The tree map file and the quality views. |
| `effects/` | The effects. |
| `engine.py` | Runs effects at a fixed frame rate. |
| `workflow.py` | The scan, reconstruct and fix steps, shared by the CLI and the viewer. |
| `jobs.py` | Runs those steps in the background for the viewer. |
| `sim/` | The tree generator and the server. |

[ROADMAP.md](ROADMAP.md) has the plan and what's next.
