"""V4L2/UVC webcam backend - works today, no vendor SDK needed. Cross-platform
discovery (Linux V4L2 device nodes on the Jetson, DirectShow indices on Windows
for local dev/testing) but both paths go through plain cv2.VideoCapture."""
from __future__ import annotations

import glob
import platform
from typing import Any

import cv2
import numpy as np

from .base import CameraBackend, ControlSpec, DeviceInfo

# name -> (cv2 property, min, max, step, unit). UVC exposure is typically a log2
# scale (-13..-1) on the DirectShow/V4L2 backends OpenCV wraps; gain/brightness are
# driver-defined 0-255 ranges. These are reasonable defaults, not device-verified.
_CONTROLS: dict[str, tuple[int, float, float, float, str]] = {
    "exposure": (cv2.CAP_PROP_EXPOSURE, -13, -1, 1, ""),
    "gain": (cv2.CAP_PROP_GAIN, 0, 255, 1, ""),
    "brightness": (cv2.CAP_PROP_BRIGHTNESS, 0, 255, 1, ""),
    "fps": (cv2.CAP_PROP_FPS, 1, 60, 1, "fps"),
}

_RESOLUTIONS = ("640x480", "1280x720", "1920x1080")


def _is_linux() -> bool:
    return platform.system() == "Linux"


class V4L2Backend(CameraBackend):
    def __init__(self) -> None:
        self._cap: cv2.VideoCapture | None = None

    @staticmethod
    def discover() -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        if _is_linux():
            for node in sorted(glob.glob("/dev/video*")):
                cap = cv2.VideoCapture(node, cv2.CAP_V4L2)
                if cap.isOpened():
                    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    devices.append(DeviceInfo(device_id=node, backend="v4l2", label=node,
                                               resolution=(w, h), extra={"device_node": node}))
                cap.release()
        else:
            for index in range(6):
                cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                if cap.isOpened():
                    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    devices.append(DeviceInfo(device_id=str(index), backend="v4l2",
                                               label=f"Camera {index}", resolution=(w, h),
                                               extra={"index": index}))
                cap.release()
        return devices

    def open(self, device: DeviceInfo) -> None:
        target = device.extra.get("device_node", device.extra.get("index"))
        flag = cv2.CAP_V4L2 if _is_linux() else cv2.CAP_DSHOW
        self._cap = cv2.VideoCapture(target, flag)
        if not self._cap.isOpened():
            raise RuntimeError(f"failed to open {device.device_id}")

    def get_frame(self) -> np.ndarray:
        if self._cap is None:
            raise RuntimeError("backend not open")
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("frame read failed")
        return frame

    def get_controls(self) -> dict[str, ControlSpec]:
        if self._cap is None:
            raise RuntimeError("backend not open")
        controls = {
            name: ControlSpec(name=name, kind="range", value=self._cap.get(prop),
                               min=lo, max=hi, step=step, unit=unit)
            for name, (prop, lo, hi, step, unit) in _CONTROLS.items()
        }
        controls["auto_wb"] = ControlSpec(name="auto_wb", kind="bool",
                                           value=bool(self._cap.get(cv2.CAP_PROP_AUTO_WB)))
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        controls["resolution"] = ControlSpec(name="resolution", kind="enum",
                                              value=f"{w}x{h}", options=_RESOLUTIONS)
        return controls

    def set_control(self, name: str, value: Any) -> None:
        if self._cap is None:
            raise RuntimeError("backend not open")
        if name == "auto_wb":
            self._cap.set(cv2.CAP_PROP_AUTO_WB, 1.0 if value else 0.0)
            return
        if name == "resolution":
            w, h = (int(n) for n in str(value).split("x"))
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            return
        self._cap.set(_CONTROLS[name][0], float(value))

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
