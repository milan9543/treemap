import numpy as np
import pytest

from treemap.cameras import Camera, Frame
from treemap.outputs import LedOutput


class RecordingOutput(LedOutput):
    def __init__(self, led_count: int) -> None:
        super().__init__(led_count)
        self.frames: list[np.ndarray] = []
        self.closed = False

    def _show(self, colors: np.ndarray) -> None:
        self.frames.append(colors.copy())

    def close(self) -> None:
        self.closed = True


class FakeCamera(Camera):
    def __init__(self, frame) -> None:
        self.frame = frame
        self.closed = False

    def _read(self, timeout):
        return Frame(0.0, self.frame)

    def close(self) -> None:
        self.closed = True


def test_abstract_classes_cannot_be_instantiated():
    with pytest.raises(TypeError):
        LedOutput(10)  # type: ignore[abstract]
    with pytest.raises(TypeError):
        Camera()  # type: ignore[abstract]


def test_output_show_passes_frame_through():
    out = RecordingOutput(4)
    colors = np.arange(12, dtype=np.uint8).reshape(4, 3)
    out.show(colors)
    assert np.array_equal(out.frames[-1], colors)
    assert out.frames[-1].flags.c_contiguous


def test_output_accepts_non_contiguous_view():
    out = RecordingOutput(4)
    big = np.arange(24, dtype=np.uint8).reshape(4, 6)
    out.show(big[:, ::2])
    assert out.frames[-1].flags.c_contiguous
    assert np.array_equal(out.frames[-1], big[:, ::2])


def test_output_fill_and_off():
    out = RecordingOutput(3)
    out.fill((255, 10, 0))
    assert out.frames[-1].tolist() == [[255, 10, 0]] * 3
    out.off()
    assert not out.frames[-1].any()


@pytest.mark.parametrize(
    "colors, exc",
    [
        (np.zeros((4, 3), dtype=np.float64), TypeError),
        (np.zeros((4, 3), dtype=np.int32), TypeError),
        (np.zeros((5, 3), dtype=np.uint8), ValueError),
        (np.zeros((4, 4), dtype=np.uint8), ValueError),
        (np.zeros(12, dtype=np.uint8), ValueError),
    ],
)
def test_output_rejects_bad_frames(colors, exc):
    out = RecordingOutput(4)
    with pytest.raises(exc):
        out.show(colors)
    assert out.frames == []


def test_output_rejects_bad_led_count():
    with pytest.raises(ValueError):
        RecordingOutput(0)


def test_output_context_manager_closes():
    with RecordingOutput(2) as out:
        out.off()
    assert out.closed


def test_camera_returns_valid_frame():
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    cam = FakeCamera(frame)
    assert cam.read(0).image is frame


@pytest.mark.parametrize(
    "frame, exc",
    [
        (np.zeros((48, 64), dtype=np.uint8), ValueError),
        (np.zeros((48, 64, 4), dtype=np.uint8), ValueError),
        (np.zeros((48, 64, 3), dtype=np.float32), ValueError),
    ],
)
def test_camera_rejects_bad_frames(frame, exc):
    with pytest.raises(exc):
        FakeCamera(frame).read(0)


def test_camera_context_manager_closes():
    with FakeCamera(np.zeros((1, 1, 3), dtype=np.uint8)) as cam:
        cam.read(0)
    assert cam.closed
