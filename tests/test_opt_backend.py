#!/usr/bin/env python3
"""Offline check for cam_bench.backends.opt - real subprocess/IPC against a stub
worker script (no optcam SDK or hardware needed), covering discover/open/capture/
set_control/close. Run: python tests/test_opt_backend.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cam_bench.backends import opt as opt_module
from cam_bench.backends.base import DeviceInfo
from cam_bench.backends.opt import OptBackend

_STUB_WORKER = r'''
import sys

if "--discover" in sys.argv:
    print("DEV D999|Stub OPT Camera", flush=True)
    sys.exit(0)

print("READY", flush=True)
last = {"exposure_us": None, "gain_db": None}
for line in sys.stdin:
    parts = line.strip().split()
    if not parts:
        continue
    if parts[0] == "CAPTURE":
        import tempfile, os, time, numpy as np
        time.sleep(0.02)  # capture takes real time; widens the reply-crosstalk window
        fd, path = tempfile.mkstemp(suffix=".npy")
        os.close(fd)
        np.save(path, np.full((2, 2, 3), 7, dtype=np.uint8))
        print(f"OK {path}", flush=True)
    elif parts[0] == "SET" and len(parts) == 3:
        last[parts[1]] = float(parts[2])
        print("OK", flush=True)
    elif parts[0] == "QUIT":
        break
    else:
        print(f"ERR unknown command: {line.strip()!r}", flush=True)
'''


def check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


class _FakeCam:
    """Stands in for optcam.Camera: the controls the worker writes, readable back."""

    def __init__(self) -> None:
        self.trigger = "CONTINUOUS"
        self.exposure_us = 20000.0
        self.gain_db = 6.0
        self.buffer_count = 8
        self._enums = {"ExposureAuto": "Continuous", "GainAuto": "Continuous"}

    def get_enum(self, name: str) -> str:
        return self._enums[name]

    def set_enum(self, name: str, value: str) -> None:
        self._enums[name] = value


class _WriteOnlyGainCam(_FakeCam):
    """Some SDKs refuse to report a control they will happily accept."""

    @property
    def gain_db(self):  # noqa: D102
        raise RuntimeError("gain_db is not readable")

    @gain_db.setter
    def gain_db(self, value):
        self._gain_db = value


def check_state_restore() -> bool:
    """The app must hand a shared camera back exactly as it found it - another project
    on the same device inherits these volatile registers until a power cycle."""
    import types

    sys.modules.setdefault("optcam", types.ModuleType("optcam"))
    from cam_bench.backends import opt_worker

    cam = _FakeCam()
    before = (cam.trigger, cam.exposure_us, cam.gain_db, cam.buffer_count,
              cam.get_enum("ExposureAuto"), cam.get_enum("GainAuto"))
    saved = opt_worker.snapshot_state(cam)

    cam.trigger = "SOFTWARE"          # what run_worker() does to the camera
    cam.set_enum("ExposureAuto", "Off")
    cam.set_enum("GainAuto", "Off")
    cam.exposure_us = 8000.0
    cam.gain_db = 0.0
    cam.buffer_count = 4

    opt_worker.restore_state(cam, saved)
    after = (cam.trigger, cam.exposure_us, cam.gain_db, cam.buffer_count,
             cam.get_enum("ExposureAuto"), cam.get_enum("GainAuto"))
    ok = check("restore_state() returns every control the worker wrote to its prior value",
                after == before)

    unreadable = _WriteOnlyGainCam()
    saved2 = opt_worker.snapshot_state(unreadable)
    unreadable.trigger = "SOFTWARE"
    opt_worker.restore_state(unreadable, saved2)   # must not raise
    ok &= check("snapshot/restore skip a control the SDK will not report",
                 "gain_db" not in saved2[0] and unreadable.trigger == "CONTINUOUS")
    return ok


def main() -> int:
    all_ok = True
    tmpdir = Path(tempfile.mkdtemp())
    stub_path = tmpdir / "stub_opt_worker.py"
    stub_path.write_text(_STUB_WORKER)

    opt_module._WORKER_SCRIPT = stub_path
    os.environ["CAM_BENCH_OPT_PYTHON"] = sys.executable

    devices = OptBackend.discover()
    all_ok &= check("discover() parses 'DEV serial|label' lines from the worker",
                     len(devices) == 1 and devices[0].device_id == "D999"
                     and devices[0].backend == "opt")

    backend = OptBackend()
    backend.open(devices[0])
    frame = backend.get_frame()
    all_ok &= check("get_frame() returns the array the stub wrote via .npy handoff",
                     frame.shape == (2, 2, 3) and frame[0, 0, 0] == 7)

    backend.set_control("exposure_us", 8000)
    all_ok &= check("set_control() round-trips through the worker's OK reply",
                     backend.get_controls()["exposure_us"].value == 8000.0)

    # get_frame() (grab thread) and set_control() (JS-API thread) share one pipe;
    # without the io lock each thread can consume the other's reply.
    errors: list[str] = []

    def capture_loop() -> None:
        for _ in range(40):
            try:
                if backend.get_frame().shape != (2, 2, 3):
                    errors.append("capture returned the wrong array")
            except Exception as e:  # noqa: BLE001
                errors.append(f"capture: {e}")

    def set_loop() -> None:
        for i in range(40):
            try:
                backend.set_control("gain_db", float(i % 24))
            except Exception as e:  # noqa: BLE001
                errors.append(f"set: {e}")
            time.sleep(0.005)  # land SETs inside the stub's capture delay

    threads = [threading.Thread(target=capture_loop), threading.Thread(target=set_loop)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    all_ok &= check("concurrent get_frame()/set_control() do not steal each other's replies",
                     not errors)
    if errors:
        print(f"        {len(errors)} error(s), first: {errors[0]}")

    backend.close()
    all_ok &= check("close() is idempotent", backend._proc is None)
    backend.close()  # must not raise

    all_ok &= check_state_restore()

    del os.environ["CAM_BENCH_OPT_PYTHON"]
    all_ok &= check("discover() returns [] gracefully when CAM_BENCH_OPT_PYTHON is unset",
                     OptBackend.discover() == [])

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
