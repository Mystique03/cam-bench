"""Video recording - a thin cv2.VideoWriter wrapper, written to from the server's
existing frame-grab loop so it never needs a second capture thread."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np


class VideoRecorder:
    def __init__(self, path: str, fps: float, frame_shape: tuple[int, int]):
        h, w = frame_shape
        fourcc = cv2.VideoWriter_fourcc(*("XVID" if path.endswith(".avi") else "mp4v"))
        self._writer = cv2.VideoWriter(path, fourcc, max(1.0, fps), (w, h))
        if not self._writer.isOpened():
            raise RuntimeError(f"could not open VideoWriter for {path}")
        self.path = path
        self.start_time = time.monotonic()
        self.frame_count = 0

    def write(self, frame_bgr: np.ndarray) -> None:
        self._writer.write(frame_bgr)
        self.frame_count += 1

    def stop(self) -> None:
        self._writer.release()

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def size_bytes(self) -> int:
        try:
            return Path(self.path).stat().st_size
        except OSError:
            return 0
