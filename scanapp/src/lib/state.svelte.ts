// The page's state: which server and device, what it said, which screen.
import { Api, normaliseServer, type Info, type Shape } from "./api";

export type Screen = "connect" | "wiring" | "scan" | "review";

function load(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: just not remembered */
  }
}

/** ?server= in the address (the link `treemap serve` prints), else the last one used. */
function initialServer(): string {
  const fromUrl = new URLSearchParams(location.search).get("server");
  return normaliseServer(fromUrl || load("server"));
}

/** ?device= in the address (the server's QR code has it), else the last one scanned. */
function initialDevice(): string {
  return new URLSearchParams(location.search).get("device") || load("device");
}

export const app = $state({
  server: initialServer(),
  device: initialDevice(),
  api: null as Api | null,
  info: null as Info | null,
  shape: "tree" as Shape,
  screen: "connect" as Screen,
  addRounds: false, // the next scan adds to the rounds so far (scanning parts again)
});

/** Remember the server and device, and put them in the address so a reload or
 * bookmark finds them. */
export function useServer(api: Api, info: Info): void {
  app.api = api;
  app.info = info;
  app.server = api.server;
  app.device = api.device;
  save("server", api.server);
  save("device", api.device);
  const url = new URL(location.href);
  url.searchParams.set("server", api.server);
  url.searchParams.set("device", api.device);
  history.replaceState(null, "", url);
}

/** Let go of the server: back to the connect screen, and no reconnecting by itself on
 * the next visit. The address stays in the box (this visit only) to connect again. */
export function disconnect(): void {
  app.api = null;
  app.info = null;
  app.device = "";
  app.screen = "connect";
  try {
    localStorage.removeItem("server");
    localStorage.removeItem("device");
  } catch {
    /* nothing remembered */
  }
  const url = new URL(location.href);
  url.searchParams.delete("server");
  url.searchParams.delete("device");
  history.replaceState(null, "", url);
}

/** Android Chrome is the only browser that can scan: it alone lets a page lock the
 * camera's exposure and white balance. */
export function browserProblem(): string | null {
  if (!window.isSecureContext) return "This page must be opened over HTTPS to use the camera.";
  if (!navigator.mediaDevices?.getUserMedia) return "This browser can't use the camera.";
  const ua = navigator.userAgent;
  const android = /Android/i.test(ua);
  const chrome = /Chrome\/\d/.test(ua) && !/EdgA|SamsungBrowser|OPR|Firefox|YaBrowser|UCBrowser/.test(ua);
  if (!android || !chrome) {
    return "Scanning needs Chrome on an Android phone. Other browsers can't hold the camera's " +
      "exposure steady, so the scan may misread the LEDs.";
  }
  return null;
}
