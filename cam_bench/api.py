"""pywebview js_api bridge - the frontend calls these as window.pywebview.api.*."""
from __future__ import annotations

import json

import cv2
import webview
import yaml

from .backends import BACKENDS, DeviceInfo
from .recorder import VideoRecorder
from .roi import Roi, to_generic_json_dict, to_yaml_dict
from .session import Session


class JsApi:
    def __init__(self, session: Session):
        self.session = session
        self.window: webview.Window | None = None   # set by app.py after window creation
        self._devices: dict[str, DeviceInfo] = {}

    def discover(self) -> list[dict]:
        found = []
        for cls in BACKENDS.values():
            for device in cls.discover():
                self._devices[device.device_id] = device
                found.append(device.model_dump())
        return found

    def select_camera(self, device_id: str, backend_override: str | None = None) -> dict:
        device = self._devices.get(device_id)
        if device is None:
            return {"ok": False, "error": f"unknown device {device_id}"}
        backend_name = backend_override or device.backend
        if self.session.backend is not None:
            self.session.backend.close()
            self.session.backend = None
        backend = BACKENDS[backend_name]()
        try:
            backend.open(device)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        self.session.backend = backend
        self.session.backend_name = backend_name
        controls = {name: spec.model_dump() for name, spec in backend.get_controls().items()}
        return {"ok": True, "controls": controls}

    def set_control(self, name: str, value: float) -> dict:
        if self.session.backend is None:
            return {"ok": False, "error": "no camera open"}
        try:
            self.session.backend.set_control(name, value)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def set_zebra(self, enabled: bool) -> None:
        self.session.zebra = bool(enabled)

    def set_roi_shape(self, shape: str) -> None:
        self.session.roi_shape = shape
        self.session.roi_points.clear()

    def add_roi_point(self, x: float, y: float) -> list[list[float]]:
        self.session.roi_points.append((x, y))
        return [list(p) for p in self.session.roi_points]

    def clear_roi(self) -> None:
        self.session.roi_points.clear()

    def export_roi(self, fmt: str, image_w: int, image_h: int) -> dict:
        if not self.session.roi_points:
            return {"ok": False, "error": "no ROI points drawn"}
        roi = Roi(shape=self.session.roi_shape, points=self.session.roi_points,
                  image_w=image_w, image_h=image_h)
        if fmt == "yaml":
            data, ext = to_yaml_dict(roi), "yaml"
        else:
            data, ext = to_generic_json_dict(roi), "json"
        path = self._save_dialog(f"roi.{ext}")
        if not path:
            return {"ok": False, "error": "cancelled"}
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False) if fmt == "yaml" else json.dump(data, f, indent=2)
        return {"ok": True, "path": path}

    def start_recording(self, fmt: str) -> dict:
        if self.session.last_frame is None:
            return {"ok": False, "error": "no live frame yet"}
        ext = "mp4" if fmt == "mp4" else "avi"
        path = self._save_dialog(f"recording.{ext}")
        if not path:
            return {"ok": False, "error": "cancelled"}
        h, w = self.session.last_frame.shape[:2]
        try:
            self.session.recorder = VideoRecorder(path, fps=15.0, frame_shape=(h, w))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": path}

    def stop_recording(self) -> dict:
        recorder = self.session.recorder
        if recorder is None:
            return {"ok": False, "error": "not recording"}
        recorder.stop()
        info = {"ok": True, "path": recorder.path, "frames": recorder.frame_count,
                 "size_bytes": recorder.size_bytes}
        self.session.recorder = None
        return info

    def recording_status(self) -> dict:
        recorder = self.session.recorder
        if recorder is None:
            return {"recording": False}
        return {"recording": True, "elapsed_sec": round(recorder.elapsed_sec, 1),
                "size_bytes": recorder.size_bytes}

    def save_frame(self) -> dict:
        if self.session.last_frame is None:
            return {"ok": False, "error": "no live frame yet"}
        path = self._save_dialog("frame.png")
        if not path:
            return {"ok": False, "error": "cancelled"}
        cv2.imwrite(path, self.session.last_frame)
        return {"ok": True, "path": path}

    def _save_dialog(self, default_name: str) -> str | None:
        if self.window is None:
            return None
        result = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename=default_name)
        return result[0] if result else None
