"""OPT Machine Vision USB3 camera backend (parent side).

`optcam` is a compiled wheel tagged to one CPython minor version, so it can't
reliably be imported in-process alongside this app's own interpreter. Instead
this launches opt_worker.py under a separate interpreter - path from the
CAM_BENCH_OPT_PYTHON env var - and talks to it over stdin/stdout. See
opt_worker.py's docstring for the line protocol.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .base import CameraBackend, ControlSpec, DeviceInfo

STARTUP_TIMEOUT_SEC = 15.0
CAPTURE_TIMEOUT_SEC = 2.0
SET_TIMEOUT_SEC = 2.0
DISCOVER_TIMEOUT_SEC = 8.0
SHUTDOWN_TIMEOUT_SEC = 3.0

_WORKER_SCRIPT = Path(__file__).resolve().parent / "opt_worker.py"

# OPT-CC1-C050-UG1-10 working ranges. Deliberately narrower than what the sensor
# accepts: the full 1us-10s span put every practical value (a production line runs
# around 27ms) inside the first 1% of the slider, so a single pixel of drag jumped
# from 27ms to 9 seconds. 200ms is ~5 fps, slow enough for any dark-scene tuning.
# ponytail: hardcoded range, read it from cam.feature_info("ExposureTime").min_value/
# .max_value if a camera needs something outside this.
_EXPOSURE_US_RANGE = (100.0, 200_000.0)
_GAIN_DB_RANGE = (0.0, 24.0)

# Pushed to the camera at open() so the panel's numbers match the hardware. The
# worker forces ExposureAuto/GainAuto off, so without this the camera would run on
# whatever was left in its flash while the UI claimed these values.
DEFAULT_EXPOSURE_US = 8000.0
DEFAULT_GAIN_DB = 0.0


def _python_bin() -> str:
    python_bin = os.environ.get("CAM_BENCH_OPT_PYTHON")
    if not python_bin:
        raise RuntimeError(
            "CAM_BENCH_OPT_PYTHON is not set - point it at the Python interpreter "
            "that has the optcam SDK installed."
        )
    return python_bin


def _run_and_capture(args: list[str], timeout: float) -> list[str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return [line for line in result.stdout.splitlines() if line.strip()]


class OptBackend(CameraBackend):
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._out_q: "queue.Queue[str | None]" = queue.Queue()
        self._exposure_us: float | None = None
        self._gain_db: float | None = None
        # get_frame() runs on the server's grab thread and set_control() on the JS-API
        # thread; both share one stdin/stdout pipe, so a request+reply pair has to be
        # atomic or one thread reads the other's reply.
        self._io_lock = threading.Lock()

    @staticmethod
    def discover() -> list[DeviceInfo]:
        try:
            python_bin = _python_bin()
        except RuntimeError:
            return []
        try:
            lines = _run_and_capture([python_bin, str(_WORKER_SCRIPT), "--discover"],
                                      DISCOVER_TIMEOUT_SEC)
        except (subprocess.TimeoutExpired, OSError):
            return []
        devices = []
        for line in lines:
            if not line.startswith("DEV "):
                continue
            serial, _, label = line[4:].partition("|")
            devices.append(DeviceInfo(device_id=serial, backend="opt",
                                       label=label or "OPT camera", extra={"serial": serial}))
        return devices

    def _pump_stdout(self) -> None:
        assert self._proc is not None
        for line in iter(self._proc.stdout.readline, ""):
            self._out_q.put(line)
        self._out_q.put(None)

    def _readline(self, timeout_sec: float) -> str | None:
        try:
            line = self._out_q.get(timeout=timeout_sec)
        except queue.Empty:
            return None
        return line if line else None

    def open(self, device: DeviceInfo) -> None:
        python_bin = _python_bin()
        serial = device.extra["serial"]
        args = [python_bin, str(_WORKER_SCRIPT), "--serial", serial,
                "--exposure-us", str(DEFAULT_EXPOSURE_US), "--gain-db", str(DEFAULT_GAIN_DB)]
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        line = self._readline(STARTUP_TIMEOUT_SEC)
        if line is None:
            self.close()
            raise RuntimeError(f"opt camera {serial}: worker did not respond in time")
        if not line.startswith("READY"):
            self.close()
            raise RuntimeError(f"opt camera {serial}: {line.strip()}")
        self._exposure_us = DEFAULT_EXPOSURE_US
        self._gain_db = DEFAULT_GAIN_DB

    def _capture_timeout_sec(self) -> float:
        """A long exposure legitimately takes longer than one frame period to come back,
        so the wait has to scale with it - stay above the worker's own wait (see
        opt_worker._frame_wait_sec) or the parent gives up on a capture still in flight."""
        exposure_sec = (self._exposure_us or DEFAULT_EXPOSURE_US) / 1e6
        return max(CAPTURE_TIMEOUT_SEC, exposure_sec * 2 + 1.0)

    def get_frame(self) -> np.ndarray:
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("opt backend not open")
        with self._io_lock:
            self._proc.stdin.write("CAPTURE\n")
            self._proc.stdin.flush()
            line = self._readline(self._capture_timeout_sec())
        if line is None or not line.startswith("OK"):
            raise RuntimeError(f"capture failed: {line.strip() if line else 'timed out'}")
        path = Path(line[3:].strip())
        try:
            return np.load(path)
        finally:
            path.unlink(missing_ok=True)

    def get_controls(self) -> dict[str, ControlSpec]:
        return {
            "exposure_us": ControlSpec(name="exposure_us", kind="range",
                                        value=self._exposure_us or DEFAULT_EXPOSURE_US,
                                        min=_EXPOSURE_US_RANGE[0], max=_EXPOSURE_US_RANGE[1],
                                        step=100, unit="us"),
            "gain_db": ControlSpec(name="gain_db", kind="range", value=self._gain_db or DEFAULT_GAIN_DB,
                                    min=_GAIN_DB_RANGE[0], max=_GAIN_DB_RANGE[1],
                                    step=0.5, unit="dB"),
        }

    def set_control(self, name: str, value: Any) -> None:
        if self._proc is None:
            raise RuntimeError("opt backend not open")
        with self._io_lock:
            self._proc.stdin.write(f"SET {name} {float(value)}\n")
            self._proc.stdin.flush()
            line = self._readline(SET_TIMEOUT_SEC)
        if line is None or not line.startswith("OK"):
            raise RuntimeError(f"set {name} failed: {line.strip() if line else 'timed out'}")
        if name == "exposure_us":
            self._exposure_us = float(value)
        elif name == "gain_db":
            self._gain_db = float(value)

    def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self._proc.stdin.write("QUIT\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
            try:
                self._proc.wait(timeout=SHUTDOWN_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=SHUTDOWN_TIMEOUT_SEC)
        self._proc = None
