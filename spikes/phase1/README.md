# Phase 1 spikes (throwaway)

Steps 1.1–1.3 of [PLAN-2.0.md](../../PLAN-2.0.md): prove that the hosted HTTPS page can
reach a plain-HTTP server on the LAN, find out which camera controls the phone really has,
and measure JPEG upload from a worker. Delete this folder once Phase 2 has settled the
real API.

- `page/`: the test page (`index.html` plus `worker.js`), deployed to
  **https://treemap-spike.pages.dev/** (Cloudflare Pages project `treemap-spike`).
- `server.py`: the LAN end. It has `/ping`, `/frames` and `/stats`, and `/report` saves
  the page's JSON report.
- `out/` (gitignored): `report-*.json` from the phone, and one sample frame per size.

## Run it

```sh
uv run python spikes/phase1/server.py          # prints the link to open on the phone
```

On the phone (Android Chrome, same Wi-Fi), open
`https://treemap-spike.pages.dev/?server=http://<mac-ip>:8765`.
`https://treemap-spike.pages.dev/#<mac-ip>` is the short form and assumes port 8765.
Allow the local network prompt and the camera, point the camera at something lit, and
tap **Run everything**. It takes about a minute, and the report ends up in `out/`.

The sections can also be run one at a time. **1.2** has a slider for every control the
camera offers, so you can watch the picture change.

To deploy again after an edit:
`wrangler pages deploy spikes/phase1/page --project-name treemap-spike --branch main`.

## What it records

- **1.1:** whether the fetch got through, its latency, and the `local-network-access`
  permission before and after. Run it once with the `targetAddressSpace` box ticked too,
  to compare.
- **1.2:** `getCapabilities()`, then each manual control is set, read back with
  `getSettings()`, and checked against the preview's brightness (`luma`), to catch
  settings that are accepted but ignored. `controlSummary` gives one line per control.
  `exposureTime` is in units of 100 µs.
- **1.3:** for 640×480 and 1280×720: the camera's fps, frames encoded and sent per
  second, MB/s, KB per frame, encode time in the worker, POST latency, and frames
  dropped. Preview smoothness is the preview's fps plus main-thread gaps over 50 ms
  ("janks"). The server's side shows the fps and MB/s it received and its decode time.
  Every frame is decoded with the existing `treemap.cameras.browser.unpack_frame`.

## Batch format (input for step 2.4)

`POST /frames` sends the frames back to back. Each frame is a u32 LE length followed by
exactly what `pack_frame` makes today: a u32 LE header length, the JSON header (`t`, `i`,
`w`, `h`), then the JPEG. The length prefix is the only addition, so `unpack_frame` reads
each frame unchanged.

## Results

Tested on this Mac with headless Chrome 157 and its fake camera (2026-11-21):

- The whole flow works from `http://localhost`. Both frame paths (track processor and
  ImageBitmap) sent 20 fps at both sizes, with no drops. Encoding took 5 ms at 640×480
  and 9–11 ms at 720p, and the server decoded a frame in about 1 ms. The fake camera's
  frames are tiny (8–13 KB), so these MB/s figures say nothing about a real phone.
- From the hosted HTTPS page to `http://10.10.10.5`, Chrome didn't hard-block the request
  as mixed content. It treated it as a Local Network Access permission ("Permission was
  denied … to access the `local` address space"). That matches the plan, but headless
  Chrome can't show the prompt, so whether the fetch gets through once allowed still
  needs the phone.

**Phone** (Galaxy S23 SM-S911B, Android 17, Chrome 157.0.8103.78, 2026-11-21). Two runs:
`out/report-20261121-215042.json`, then `out/report-20261121-215615.json` with the probes,
both rear cameras, and the batches POSTed from the page.

### 1.1 Local network from HTTPS: done

- From the page, everything works once the permission is allowed: `GET` 200 in 15–44 ms,
  and `POST` with JSON or octet-stream (so with a CORS preflight). A plain IP address needs
  no `targetAddressSpace`.
- **From a dedicated worker, every fetch fails** in 0–2 ms (GET and POST, with or without
  `targetAddressSpace: "local"`), even with the permission granted. **So all fetches must
  come from the page itself.** The worker can still do the encoding.

### 1.2 Camera controls: done

| | camera 0, facing back (main) | camera 2, facing back (wide) |
|---|---|---|
| Chosen by `facingMode: environment` | no | **yes** |
| exposureMode | manual works; reads back as `"none"` | same |
| exposureTime (100 µs units) | 0.5–1500, set exactly; the picture follows | same |
| iso | 50–3200, set exactly; the picture follows | same |
| exposure time + iso together | works (5.5 + 838) | works |
| exposureCompensation | −2 to +2, works | same |
| white balance | locks only with a `colorTemperature`, and snaps to presets (3000 → 2850, 5500 → 5000). `whiteBalanceMode: "manual"` on its own is ignored, and `continuous` doesn't come back until the camera is reopened. | same |
| focus | continuous, single-shot, manual; distance 0.1–4.05 | fixed (manual only, 0–0.79) |
| torch | yes | no |
| zoom | 1–8 | 1–8 |

Frames are portrait (480×640, 720×1280) and arrive upright.

### 1.3 Frame upload: done

Encoded in the worker (MediaStreamTrackProcessor), POSTed from the page every 250 ms,
quality 0.8, camera 2 on auto exposure in a dim room:

| | 480×640 | 720×1280 |
|---|---|---|
| camera fps / sent fps | 24.6 / 24.6 | 24.4 / 24.4 |
| frames dropped | 0 | 0 |
| KB per frame | 43 | 97 |
| upload | 1.08 MB/s | 2.43 MB/s |
| encode (worker, median) | 15 ms | 22 ms |
| POST latency (median) | 76 ms | 121 ms |
| preview | 24.7 fps, no gaps over 50 ms | 24.2 fps, one gap (75 ms) |
| server decode (Mac) | 1.2 ms | 2.7 ms |

The camera gave 24–25 fps against 30 asked for, likely because auto exposure was using
30 ms frames in the dim room. With a short locked exposure it should reach 30; not measured.

### What this changes in the plan

- All fetches come from the page; the worker only encodes.
- The scan page picks the main camera itself (the one with continuous focus), since
  `facingMode: environment` gave the wide one.
- Lock white balance with a `colorTemperature` (a preset), not with the mode alone.
- Treat `exposureMode: "none"` as manual.
- 720p at 2.4 MB/s is fine. The plan's fallback (WebCodecs/H.264) isn't needed.
