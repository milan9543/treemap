import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import pytest

from treemap.cameras.android import AndroidCamera, CameraUnavailable, split_jpegs
from treemap.cameras.base import Camera, Frame
from treemap.cameras.check import advice, colour_check, solid
from treemap.scan.colours import ColourModel
from treemap.scan.track import find_blobs
from treemap.outputs.base import LedOutput


def jpeg(value: int) -> bytes:
    img = np.full((48, 64, 3), value, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_split_jpegs_across_chunks():
    a, b = jpeg(10), jpeg(200)
    stream = b"--boundary\r\nContent-Type: image/jpeg\r\n\r\n" + a + b"\r\n--boundary\r\n\r\n" + b
    buf, out = bytearray(), []
    for i in range(0, len(stream), 100):  # arrives in pieces
        buf += stream[i:i + 100]
        out += split_jpegs(buf)
    assert out == [a, b]


@pytest.fixture
def ipwebcam():
    """A stand-in for the IP Webcam app: /video streams JPEGs, settings are remembered."""
    settings = {"exposure_lock": "off", "whitebalance_lock": "off", "video_size": "64x48"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/video":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=b")
                self.end_headers()
                try:
                    for k in range(1000):
                        self.wfile.write(b"--b\r\nContent-Type: image/jpeg\r\n\r\n"
                                         + jpeg(k % 250) + b"\r\n")
                        time.sleep(0.02)
                except OSError:
                    pass
            elif self.path == "/status.json":
                self._json('{"curvals": %s}' % str(settings).replace("'", '"'))
            elif self.path.startswith("/settings/"):
                key, _, value = self.path.removeprefix("/settings/").partition("?set=")
                settings[key] = value
                self._json("{}")
            else:
                self.send_error(404)

        def _json(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", settings
    server.shutdown()


def test_reads_frames_and_locks_exposure(ipwebcam):
    url, settings = ipwebcam
    with AndroidCamera(url) as cam:
        frames = [cam.read(timeout=1) for _ in range(5)]
        assert all(f is not None and f.image.shape == (48, 64, 3) for f in frames)
        assert frames[-1].t > frames[0].t
        assert cam.settings()["video_size"] == "64x48"
        assert cam.locked() is False
        assert cam.lock(True) and cam.locked()
    assert settings["exposure_lock"] == "on" and settings["whitebalance_lock"] == "on"


def test_unreachable_phone_is_a_clear_error():
    with pytest.raises(CameraUnavailable, match="Is IP Webcam running"):
        AndroidCamera("http://127.0.0.1:9", connect_timeout=1.5)


class Mirror(LedOutput, Camera):
    """LEDs and a camera in one: each frame films the LEDs as a row of dots, optionally
    washing their colours out towards white like a phone's JPEGs."""

    def __init__(self, n: int, washed: float = 0.0):
        LedOutput.__init__(self, n)
        self.colors = np.zeros((n, 3), np.uint8)
        self.washed = washed

    def _show(self, colors):
        self.colors = colors.copy()

    def _read(self, timeout):
        time.sleep(0.04)
        img = np.zeros((60, 20 * len(self.colors), 3), np.uint8)
        for i, c in enumerate(self.colors):
            rgb = c.astype(float)
            rgb = (1 - self.washed) * rgb + self.washed * rgb.max()
            cv2.circle(img, (10 + 20 * i, 30), 3, tuple(float(v) for v in rgb[::-1]), -1)
        return Frame(time.monotonic(), cv2.GaussianBlur(img, (0, 0), 1.5))


def test_measured_colours_read_a_washed_out_camera_that_thresholds_misread(tmp_path):
    cam = Mirror(20, washed=0.6)  # green arrives as about (96, 160, 96)
    results, model = colour_check(cam, cam, 160, settle_s=0.1, sample_s=0.3)
    assert [r.share for r in results] == [1.0] * 4
    assert advice(24.0, (640, 480), results, model, 160) == []
    cam.show(solid(20, 1, 160))  # green, read with the default thresholds
    blobs = find_blobs(cam.read(1).image)
    assert (blobs.sym == 3).all()  # thresholds call it white
    assert (model.classify(blobs.rgb) == 1).all()

    model.save(tmp_path / "colours.json")
    assert np.allclose(ColourModel.load(tmp_path / "colours.json").centres, model.centres,
                       atol=1e-4)
