"""Image-quality helpers: focus score, histogram, exposure-clipping (zebra) overlay."""
from __future__ import annotations

import cv2
import numpy as np


def focus_score(frame_bgr: np.ndarray) -> float:
    """Laplacian variance - higher means sharper. Not an absolute unit, only useful
    for comparing frames from the same scene/lighting (e.g. two lens candidates)."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def histogram(frame_bgr: np.ndarray, bins: int = 24) -> list[float]:
    """Grayscale histogram, bin counts normalized 0-1 against the tallest bin."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [bins], [0, 256]).flatten()
    peak = hist.max()
    if peak <= 0:
        return [0.0] * bins
    return (hist / peak).tolist()


def apply_zebra(frame_bgr: np.ndarray, high: int = 250, low: int = 5) -> np.ndarray:
    """Highlight blown-out (>=high) and crushed (<=low) pixels with a diagonal stripe
    pattern - the camera-gear convention for spotting exposure clipping at a glance."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    clipped = (gray >= high) | (gray <= low)
    if not clipped.any():
        return frame_bgr
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w]
    stripes = ((xx + yy) // 6) % 2 == 0
    out = frame_bgr.copy()
    out[clipped & stripes] = (0, 210, 255)  # amber, BGR
    return out
