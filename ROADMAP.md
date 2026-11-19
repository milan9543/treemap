# treemap: WLED Christmas tree 3D/2D mapping

**Goal:** map the real position of each of 400 WLED LEDs (2 × 200 strips) on a Christmas tree with a phone camera, then run position-aware effects streamed from Python. Everything is built and tested in a **simulator first**, because the hardware isn't here yet.

**Stack:**
- Python with uv; numpy, opencv-python, typer, pyyaml, requests, websockets.
- A browser 3D viewer (three.js from a CDN).

**Core design rule:** all hardware sits behind two interfaces.
- **`LedOutput`**, which shows colours, has two implementations: `SimOutput` (the browser viewer) and `WledOutput` (DDP over UDP).
- **`Camera`**, a stream of frames, has two implementations: `BrowserCamera` (the viewer's virtual phone, which you walk round the simulated tree) and `AndroidCamera` (the IP Webcam app).

Scan, reconstruction, diagnostics and effects never know whether they're running in the simulator or on the real tree. `config.yaml` selects the mode, and sim is the default.

### Planned layout
```
treemap/
  pyproject.toml  config.yaml  ROADMAP.md
  treemap/
    cli.py config.py engine.py
    outputs/  base.py sim.py ddp.py wled.py
    cameras/  base.py sim.py android.py
    sim/      tree.py server.py viewer/index.html
    scan/     capture.py detect.py reconstruct.py cleanup.py evaluate.py
    mapping/  model.py ledmap_export.py
    effects/  base.py registry.py diagnostics.py plane.py spiral.py ...
  data/   sim_tree.json  scans/<profile>/  tree_map.json
  tests/
```

### Phase A: simulator (no hardware needed)

#### Batch 1: project skeleton and interfaces
- Set up the uv project, the `treemap` CLI (typer), and `config.yaml` loading. Config keys: `led_count`, `output: sim|wled`, `controllers[]` (host, start, count, reverse), `camera: {type, url}`, `scan`, `sim`.
- Abstract base classes: `LedOutput.show(colors: (N,3) uint8)` and `Camera.capture() -> BGR frame`.
- **Done when:** `treemap --help` works and pytest runs.

#### Batch 2: random tree and 3D viewer
- `sim/tree.py`, a seeded random tree generator:
  - Cone height 1.5–2.2 m and radius 0.5–0.8 m, both randomised.
  - Two strands of 200 LEDs as noisy, irregular spirals, with zig-zags into and out of branches.
  - Optional wiring quirks: a reversed strand, or a strand starting at the top.
  - Saves the ground truth to `data/sim_tree.json`.
- `sim/server.py` and `viewer/index.html`:
  - A local http and websocket server.
  - A three.js scene with glowing LED sprites, a faint cone and orbit controls.
  - A toggle between ground-truth and reconstructed positions.
- `SimOutput` streams colour frames to the viewer.
- Test patterns: `treemap test chase | led N | all-white | off`.
- **CLI:** `treemap sim new [--seed]`, `treemap sim view`.
- **Done when:** a random tree appears in the browser and the chase runs 0 → 399.

#### Batch 3: simulated camera and scan capture
- `SimCamera` renders a synthetic photo from view angle θ:
  - Perspective projection with the LEDs that are currently lit drawn as Gaussian blobs.
  - Noise and ambient light.
  - LEDs behind the trunk are attenuated, and random per-view foliage occlusion is applied.
  - A few false blobs or reflections are added.
- `scan/capture.py`, the same for sim and real hardware. For each angle:
  - Capture a dark reference.
  - For each LED: light it, wait for it to settle, capture, diff against the dark reference, detect.
  - Supports resume and subset rescans with `--leds 120-140`.
- `scan/detect.py`: blur, then a blob centroid giving (u, v, confidence) from SNR and compactness.
- Output: `data/scans/<profile>/angle_XXX.json` and a debug overlay PNG.
- After each angle, the LEDs detected in that view flash **green**.
- **CLI:** `treemap scan [--angle θ] [--leds a-b]`.
- **Done when:** a sim scan of 4 angles produces detections and debug images.

#### Batch 4: 3D reconstruction and cleanup
- Weak-perspective model: `u_θ − c_θ = s·(X cosθ + Z sinθ)`, with v giving height. The trunk axis `c_θ` is auto-detected from opposite views.
- Confidence-weighted least squares per LED.
- Cleanup:
  - Adjacent LEDs sit at most ~10 cm apart, so a larger jump marks an outlier.
  - Outliers are re-interpolated along the strand index.
  - Each LED gets a status: `ok`, `interpolated` or `failed`.
- Normalise: y runs 0 → 1, x and z are centred on the trunk with the same scale. Output is `tree_map.json`.
- `treemap sim evaluate`: median and p95 error versus ground truth, plus counts per status.
- **Done when:** the median error is under 2% of tree height on random trees, as an automated test.

#### Batch 5: mapping-quality display
- `treemap show-mapping`: **green** = ok, **yellow** = interpolated, **red** = failed. It prints a summary and the indices of problem LEDs.
- `treemap show-mapping --verify`: a slowly rising horizontal plane, then a left-to-right sweep. A mis-mapped LED lights out of step with its neighbours.
- `treemap fix N`: lights LED N blue with its neighbours dim, then offers to rescan or interpolate it.
- **Done when:** the virtual tree shows mostly green and injected bad LEDs show yellow or red.

#### Batch 6: effects engine and first 3D effects
- `TreeMap` model: xyz, cylindrical (r, θ, h), front uv and status, as vectorised numpy.
- `Effect.render(t, map) -> (N,3) uint8`, with a registry and `--param k=v`.
- Engine: fixed fps (default 40), brightness, gamma, crossfade, clean exit.
- Effects:
  - `plane`: an axis sweep, or rotating around the trunk.
  - `rainbow3d`
  - `spiral`: helix and candy cane.
  - `sphere`: bursts.
- **CLI:** `treemap run <effect> [--map truth|scanned]`.
- **Done when:** the effects look right in the viewer on both the true and the scanned map.

#### Batch 7: more effects, 2D and playlists
- More effects: `snow`, `fire`, `twinkle`.
- `image2d`: projects an image or GIF from the front (uv) or wrapped around the tree (θ, h).
- Playlists: `treemap playlist playlist.yaml` rotates effects with crossfades.
- **Done when:** a playlist runs smoothly in the viewer.

#### Batch 8: WLED output (ready before the hardware)
- DDP encoder: 10-byte header, push flag on the last packet, ≤480 px per packet, UDP port 4048.
- `WledOutput`: splits the 400 global LEDs across one or two controllers and handles reversed strands. JSON API helpers read `/json/info` and set `/json/state`.
- **Done when:** unit tests cover packet encoding and splitting across controllers.

### Phase B: real hardware (once WLED and the LEDs arrive)

#### Batch 9: Android camera
- **`AndroidCamera`** reads the "IP Webcam" Android app's MJPEG stream (`{url}/video`) into the `Camera.read()` stream, timestamping frames on arrival. The scan decodes from colour changes, not timing, so stream lag doesn't matter.
  - It tries to lock exposure, white balance and focus through the app's endpoints, and otherwise asks you to set them by hand.
  - `show_detections` could later draw the scan's detections on the phone.
- **`treemap camera check`** saves a few frames and reports the frame rate and colour separation of a red/green/blue test pattern.
- This batch can be done with the phone alone, before WLED arrives.
- **Done when:** frames arrive reliably over Wi-Fi at 20+ fps.

#### Batch 10: real tree session
- Set `output: wled` and `camera: android`, then:
  - `test chase` to confirm the index order;
  - `treemap scan`, walking round the tree with the phone in a dark room;
  - `show-mapping` and `--verify`;
  - fix problem LEDs;
  - run the effects and playlist.
- **Done when:** a rising plane looks level on the real tree.

#### Batch 11 (optional): native WLED 2D fallback
- `treemap export-ledmap --grid 20x25` writes a WLED `ledmap.json` from the front projection, so WLED's built-in 2D effects work without a computer.

### Ideas backlog
- Later scan rounds could flash only the LEDs that aren't ok yet, with shorter codes.
- Use the phone's motion sensors (or its horizon) to fix "up" more firmly.
- A Raspberry Pi deployment as a systemd service.
- A web UI to pick effects and tune their parameters from a phone.

