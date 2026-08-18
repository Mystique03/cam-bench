"""GigE Vision backend - stub. No GigE hardware to build/test against yet, so this
raises on open() rather than pretending to work. discover() returns [] rather than
raising: "no GigE cameras found" is a normal, non-error state for a rescan."""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import CameraBackend, ControlSpec, DeviceInfo


class GigeBackend(CameraBackend):
    @staticmethod
    def discover() -> list[DeviceInfo]:
        return []

    def open(self, device: DeviceInfo) -> None:
        raise NotImplementedError("GigE Vision is not yet supported")

    def get_frame(self) -> np.ndarray:
        raise NotImplementedError("GigE Vision is not yet supported")

    def get_controls(self) -> dict[str, ControlSpec]:
        raise NotImplementedError("GigE Vision is not yet supported")

    def set_control(self, name: str, value: Any) -> None:
        raise NotImplementedError("GigE Vision is not yet supported")

    def close(self) -> None:
        pass
