// The phone's rear camera, for filming the LEDs.
//
// `facingMode: "environment"` can give the fixed-focus wide lens (it did on a Galaxy S23),
// so the main camera is picked by hand: the first rear camera with continuous focus. The
// choice is remembered. The scan sets the exposure for the LEDs (see exposure.ts).

import { save } from "./state.svelte";

const SIZE = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } };
const REAR = /back|rear|environment/i;

export interface Camera {
  stream: MediaStream;
  track: MediaStreamTrack;
  label: string;
  width: number;
  height: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function open(video: MediaTrackConstraints): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({ video: { ...SIZE, ...video }, audio: false });
}

function hasContinuousFocus(track: MediaStreamTrack): boolean {
  const caps = (track.getCapabilities?.() ?? {}) as { focusMode?: string[] };
  return !!caps.focusMode?.includes("continuous");
}

function stop(stream: MediaStream): void {
  stream.getTracks().forEach((t) => t.stop());
}

function describe(stream: MediaStream): Camera {
  const track = stream.getVideoTracks()[0];
  const s = track.getSettings();
  return { stream, track, label: track.label, width: s.width ?? 0, height: s.height ?? 0 };
}

export async function openRearCamera(): Promise<Camera> {
  let remembered = "";
  try {
    remembered = localStorage.getItem("camera") ?? "";
  } catch {
    /* not remembered */
  }
  if (remembered) {
    try {
      return describe(await open({ deviceId: { exact: remembered } }));
    } catch {
      /* gone, or not allowed: pick again */
    }
  }

  let stream = await open({ facingMode: { ideal: "environment" } });
  await sleep(500); // Android reports the full capabilities only once the camera runs
  if (!hasContinuousFocus(stream.getVideoTracks()[0])) {
    const current = stream.getVideoTracks()[0].getSettings().deviceId;
    const rear = (await navigator.mediaDevices.enumerateDevices())
      .filter((d) => d.kind === "videoinput" && REAR.test(d.label) && d.deviceId !== current)
      .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
    for (const d of rear) {
      let other: MediaStream;
      try {
        stop(stream); // phones open one camera at a time
        other = await open({ deviceId: { exact: d.deviceId } });
      } catch {
        stream = await open({ facingMode: { ideal: "environment" } });
        continue;
      }
      await sleep(500);
      if (hasContinuousFocus(other.getVideoTracks()[0])) {
        stream = other;
        break;
      }
      stop(other);
      stream = await open({ facingMode: { ideal: "environment" } });
    }
  }
  const cam = describe(stream);
  const id = cam.track.getSettings().deviceId;
  if (id) save("camera", id);
  return cam;
}

/** The camera's name for people: "camera2 0, facing back" → "camera 0, facing back". */
export function cameraName(label: string): string {
  return label.replace(/^camera2 /, "camera ") || "camera";
}
