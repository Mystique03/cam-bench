"""Camera backend interface - every camera type (V4L2, OPT, GigE, ...) subclasses
CameraBackend, so the server/UI code never branches on backend type."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from pydantic import BaseModel


class DeviceInfo(BaseModel):
    device_id: str          # stable id for this run (e.g. "USB0", a V4L2 index or path)
    backend: str             # "v4l2" | "opt" | "gige"
    label: str                # human-readable, shown in the device list
    resolution: tuple[int, int] | None = None
    status: str = "idle"      # "idle" | "live" | "unreachable"
    extra: dict[str, Any] = {}   # backend-specific (serial, device node, ...)


class ControlSpec(BaseModel):
    name: str
    kind: str                 # "range" | "bool" | "enum"
    value: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    options: tuple[str, ...] = ()   # for kind == "enum"


class CameraBackend(ABC):
    """Subclass this per camera type. See v4l2.py/opt.py/gige.py."""

    @staticmethod
    @abstractmethod
    def discover() -> list[DeviceInfo]: ...

    @abstractmethod
    def open(self, device: DeviceInfo) -> None: ...

    @abstractmethod
    def get_frame(self) -> np.ndarray: ...

    @abstractmethod
    def get_controls(self) -> dict[str, ControlSpec]: ...

    @abstractmethod
    def set_control(self, name: str, value: Any) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
