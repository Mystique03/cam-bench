"""Shared mutable state between the js_api bridge (api.py) and the local HTTP
server (server.py) - both operate on the same active camera backend."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .backends import CameraBackend
from .recorder import VideoRecorder


@dataclass
class Session:
    backend: CameraBackend | None = None
    backend_name: str | None = None
    zebra: bool = False
    roi_shape: str = "quad"
    roi_points: list[tuple[float, float]] = field(default_factory=list)
    recorder: VideoRecorder | None = None
    last_frame: np.ndarray | None = None   # written by server's grab loop, read by api.py
