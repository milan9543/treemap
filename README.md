# treemap

Map where each LED of a WLED Christmas tree really is, using a phone camera, then run
effects that use those 3D positions: a plane sweeping up the tree, a rainbow turning
round it, and so on.

Everything also runs in a **simulator**: a random virtual tree in a browser 3D viewer,
photographed by a virtual camera. You can try the whole workflow (scan, reconstruct,
check, fix, run effects) before the hardware arrives.

> **Status:** the simulator, scanning, reconstruction, mapping checks and the effects
> engine all work. The WLED output (`output: wled`) and the Android camera
> (`camera: android`) aren't built yet; see [ROADMAP.md](ROADMAP.md).

## Install

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```sh
uv sync
uv run treemap --help
```

Every command below is run as `uv run treemap …` from the project folder.

## Quick start: the web viewer

```sh
uv run treemap sim view
```

This opens the viewer at <http://127.0.0.1:8765/>. If there's no simulated tree yet, it
generates one. Leave it running: the viewer can do everything the command line can.

1. **Tree** panel (top right): set up the strips, size and layout, then press
   **Generate**. Leave a field blank to randomise it.
2. **Scan** panel (below it): press **Scan**. Each LED lights in turn while the virtual
   camera photographs the tree from every angle (0°, 90°, 180° and 270° by default).
   About 3 seconds per angle for 400 LEDs. The found LEDs flash green after each angle.
3. Press **Reconstruct** to work out the 3D positions. This writes `data/tree_map.json`.
4. **Mapping** panel (left):
   - **Status colours** lights each LED green (ok), yellow (interpolated) or red
     (failed).
   - **Verify sweep** runs a plane up the tree and then left to right. An LED that
     lights out of step with its neighbours is in the wrong place.
   - **Evaluate** compares the map with the simulated tree's true positions.
   - Click a problem LED (or any LED in the 3D view) to light it blue and see what
     each view saw of it. Then **Rescan** it, or **Interpolate** it from its
     neighbours.
5. **Truth / Scanned** (top left, or the `t` key) switches between the true positions
   and the reconstructed ones.
6. **Effects** panel: click an effect to run it; its controls appear below. **Stop**
   turns the LEDs off.

Other controls: drag to orbit, scroll to zoom, `r` resets the view, `o` shows or hides
unlit LEDs, `c` the cone and `w` the wire path. **Config** shows the effective settings.

## The same from the command line

Keep `treemap sim view` running in one terminal to watch; run these in another.

| Step | Command |
|---|---|
| Make a new random tree | `treemap sim new [--seed 42] [--strip 200:14:top …]` |
| Check the wiring order | `treemap test chase`, `treemap test led 57`, `treemap test off` |
| Scan | `treemap scan` |
| Scan one angle, or some LEDs again | `treemap scan --angle 90 --leds 120-140` |
| Start a scan over | `treemap scan --fresh` |
| Reconstruct | `treemap reconstruct` |
| Show the mapping quality | `treemap show-mapping` (add `--verify` for the sweep) |
| Inspect and fix one LED | `treemap fix 57` (asks: rescan, interpolate or keep) |
| Accuracy against the simulator | `treemap sim evaluate` |
| List effects | `treemap effects` |
| Run an effect | `treemap run rainbow -p speed=0.5 --seconds 30` |
| Show the config | `treemap config show` |

An interrupted scan resumes where it stopped: run the same command again.

## What the statuses mean

| Status | Meaning |
|---|---|
| **ok** | Seen clearly from at least two directions; placed to within a few mm in the simulator. |
| **interpolated** | Not measured well (hidden, a reflection, or a short gap). Placed between its neighbours on the strip. Usually within a few cm. |
| **failed** | A longer gap, a strip end or the join between two strips. The position is only a rough guess. |

To deal with a yellow or red LED, select it in the Mapping panel or run `treemap fix N`:

- **Rescan** photographs it again from every scanned angle and rebuilds the map.
- **Interpolate** ignores its detections from now on, for example a reflection the
  camera keeps picking up. It's stored in `data/scans/<profile>/overrides.json`;
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
| `camera.type`, `camera.url` | `sim`, or `android` with the IP Webcam URL (not built yet). |
| `scan.angles` | View angles in degrees. Default `[0, 90, 180, 270]`. |
| `scan.profile` | Scans are kept in `data/scans/<profile>/`. |
| `scan.settle_ms` | Wait after lighting an LED before the photo (real camera only). |
| `scan.min_confidence` | Detections below this count as weak and aren't used. |
| `engine.fps`, `engine.brightness`, `engine.crossfade` | Effects frame rate, overall brightness 0–1, and the blend time when switching effects. |
| `sim.strips`, `sim.height`, `sim.radius`, `sim.layout`, `sim.seed` | Defaults for generated trees (`null` = random). |
| `sim.occlusion` | 0–1: how much foliage hides LEDs that aren't facing the virtual camera. |
| `sim.hidden_leds` | LEDs the virtual camera never sees, e.g. `"57, 120-127"`, to try out fixing bad LEDs. |

## Files

| Path | Contents |
|---|---|
| `data/sim_tree.json` | The simulated tree: true LED positions and how it was wired. |
| `data/scans/<profile>/angle_XXX.json` | Where each LED was found in that view: `ok`, `weak` or `missing`, with pixel position and confidence. |
| `data/scans/<profile>/angle_XXX_debug.png` | Every LED's light combined into one picture, with the detections marked. Long lines jumping across it point at wrong detections. |
| `data/scans/<profile>/overrides.json` | LEDs you asked to interpolate. |
| `data/tree_map.json` | The result: a position and status per LED. Heights run 0 (lowest LED) to 1 (highest); x and z are centred on the trunk at the same scale. |

## Scanning the real tree (once the hardware is supported)

The scan works the same way; only the output and camera change (`output: wled`,
`camera: android`). Things that matter for a good result:

- A dark room, with the phone on a tripod at about trunk height, a couple of metres
  away, and the whole tree in the frame.
- Keep the phone at the same distance and height for every angle. Rotating the tree on
  its stand is easiest. A few degrees off is fine; the reconstruction corrects it.
- Angle convention: angle 0 is your first view. Going to 90° means walking a quarter
  turn **clockwise** round the tree seen from above, or turning the tree a quarter
  turn **anticlockwise**.
- The viewer (or the terminal) asks you to move the camera before each angle; press
  **Continue** (or Enter) when it's in place.
- Run `treemap test chase` first to check the LED order, and look at the debug images
  after scanning.

## Troubleshooting

- **The LEDs flicker between two patterns, or the status colours blink over an
  effect.** Two programs are sending colours at once, typically a
  `treemap show-mapping` or `treemap test …` still running in a terminal. The viewer
  names them in a warning; stop all but one (Ctrl-C in its terminal).
- **"sim viewer not reachable"**: start `treemap sim view`. The command still works
  without it; you just can't watch.
- **"the simulated tree has N LEDs but led_count is M"**: make `led_count` match the
  strips, then generate a new tree.
- **Scan refused with "scanned with N LEDs" or a different photo size**: the earlier
  results don't fit. Scan again with **Start over** (`--fresh`).
- **The viewer still shows the old version after an update**: restart
  `treemap sim view` and reload the page.

## Development

```sh
uv run pytest
```

The code is in `treemap/`:

| Module | Contents |
|---|---|
| `cameras/` | The camera interface and the simulated camera. |
| `outputs/` | The LED output interface and the viewer output. |
| `scan/` | Capture, detection, reconstruction, cleanup and evaluation. |
| `mapping/` | The tree map file and the quality views. |
| `effects/` | The effects. |
| `engine.py` | Runs effects at a fixed frame rate. |
| `workflow.py` | The scan, reconstruct and fix steps, shared by the CLI and the viewer. |
| `jobs.py` | Runs those steps in the background for the viewer. |
| `sim/` | The tree generator, the server and the viewer page. |

[ROADMAP.md](ROADMAP.md) has the plan and what's next.
