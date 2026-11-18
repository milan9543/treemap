"""Find the one lit LED in a photo, given a dark reference of the same view.

The dark frame is subtracted (so room lights and anything static cancel out), the
difference is blurred, and the connected blob around the brightest point is taken as
the LED. Its intensity-weighted centroid is the position; the confidence combines:

* **SNR**: how far the peak stands above the noise of the difference image;
* **dominance**: the share of all bright-blob energy in that blob (a reflection or a
  stray flash elsewhere lowers it);
* **roundness**: an LED is a round spot, a smear or merged blobs is elongated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

MIN_SNR = 6.0  # below this the peak is indistinguishable from noise: nothing found
FULL_SNR = MIN_SNR * 8  # SNR at which the SNR part of the confidence reaches 1


@dataclass
class Detection:
    u: float  # px, from the left edge (pixel centres are at whole numbers)
    v: float  # px, from the top edge
    confidence: float  # 0-1
    snr: float
    area: int  # px in the blob


def difference(lit: np.ndarray, dark: np.ndarray) -> np.ndarray:
    """Signed brightness change ``lit − dark`` as float32 grey (mean of the channels)."""
    if lit.shape != dark.shape:
        raise ValueError(f"lit frame {lit.shape} and dark frame {dark.shape} differ in size")
    return (lit.astype(np.float32) - dark.astype(np.float32)).mean(axis=2)


def detect(
    lit: np.ndarray, dark: np.ndarray, blur_sigma: float = 1.5, min_snr: float = MIN_SNR
) -> Detection | None:
    """The lit LED's position in ``lit`` (BGR), or None if nothing stands out."""
    blurred = cv2.GaussianBlur(difference(lit, dark), (0, 0), blur_sigma)
    sample = blurred[::4, ::4]
    level = float(np.median(sample))
    noise = max(float(np.median(np.abs(sample - level))) * 1.4826, 0.05)

    y, x = np.unravel_index(int(np.argmax(blurred)), blurred.shape)
    peak = float(blurred[y, x]) - level
    snr = peak / noise
    if snr < min_snr:
        return None

    thresh = level + max(5 * noise, 0.2 * peak)
    mask = (blurred > thresh).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    weight = np.where(mask > 0, blurred - thresh, 0.0)
    energy = np.bincount(labels.ravel(), weights=weight.ravel(), minlength=n)
    best = int(labels[y, x])

    bx, by, bw, bh, area = (int(s) for s in stats[best])
    w = weight[by : by + bh, bx : bx + bw] * (labels[by : by + bh, bx : bx + bw] == best)
    total = float(w.sum())
    ys, xs = np.mgrid[by : by + bh, bx : bx + bw]
    u = float((w * xs).sum() / total)
    v = float((w * ys).sum() / total)

    cov = np.cov(np.stack([xs.ravel(), ys.ravel()]), aweights=w.ravel() + 1e-12)
    eig = np.linalg.eigvalsh(np.atleast_2d(cov))
    roundness = math.sqrt(max(eig[0], 0.0) / eig[-1]) if eig[-1] > 1e-9 else 1.0
    dominance = float(energy[best] / energy[1:].sum())
    snr_score = min(math.log(snr / min_snr) / math.log(FULL_SNR / min_snr), 1.0)
    confidence = snr_score * dominance * (0.6 + 0.4 * roundness)
    return Detection(u=u, v=v, confidence=round(confidence, 4), snr=round(snr, 1), area=area)
